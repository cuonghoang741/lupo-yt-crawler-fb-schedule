"""Bộ điều phối: nối ba module — cào+tải (crawl), render (render), đăng Facebook (upload) —
theo khung giờ và lưu lịch sử. Mọi thao tác Facebook chạy trên một luồng riêng (Playwright sync)."""
from __future__ import annotations

import json
import copy
import queue
import random
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import crawl  # Module 1 — tự cào + tải
import render  # Module 2 — render (gọi Frame Preview)
import upload  # Module 3 — đăng Facebook
import ytcore
import accounts

STATE = ytcore.app_dir() / "automation.json"
LOG_DIR = ytcore.app_dir() / "logs"
DEFAULTS = {
    "channels": [],
    "scan_minutes": 15,
    "seen": {},  # kênh -> [video id]; lần quét đầu chỉ lấy mốc, không tải lịch sử kênh
    "posts": {},  # "videoId|pageUrl" -> {state, url, at, error, title, page, fails, file, rendered}
    "show_browser": False,  # hiện cửa sổ trình duyệt khi bot chạy, để dễ gỡ lỗi
    "render_enabled": False,  # Module 2: reframe bằng Frame Preview trước khi đăng
    "render_ratio": "9:16",
    "render_fit": "blur",  # blur = nền mờ, crop = cắt, pad = viền
    "frame_dir": "",  # thư mục Frame Preview; để trống thì tự dò
    "downloads": [],  # lịch sử tải: [{at, title, channel, url, file, status}]
}
MAX_FAILS = 2
MAX_DOWNLOAD_HISTORY = 500
SLOT_GRACE = timedelta(minutes=30)
READ_EVERY = 3600


def parse_keywords(text: str) -> list[str]:
    keywords = list(dict.fromkeys(k.strip() for k in re.split(r"[,\n]+", text) if k.strip()))
    if len(keywords) > 100 or any(len(k) > 100 for k in keywords):
        raise ValueError("Tối đa 100 từ khóa, mỗi từ khóa tối đa 100 ký tự.")
    return keywords


def parse_pages(text: str) -> list[dict]:
    """Mỗi dòng `Tên Page | https://www.facebook.com/...`. Link có Page ID giúp xác minh chính xác hơn."""
    pages = []
    for i, line in enumerate(l.strip() for l in text.splitlines()):
        if not line or line.startswith("#"):
            continue
        name, _, url = (part.strip() for part in line.partition("|"))
        if not url or not re.match(r"^https://(www\.|m\.)?facebook\.com/", url):
            raise ValueError(f"Dòng Page {i + 1}: cần dạng Tên Page | https://www.facebook.com/…")
        pages.append({"name": name, "url": url.split("#")[0]})
    return pages


def parse_slots(text: str) -> list[str]:
    slots = []
    for part in re.split(r"[,\s;]+", text.strip()):
        if not part:
            continue
        # 08:00, 8.30, 20h, 20h30
        m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2})|h(\d{2})?)", part, re.I)
        minute = (m[2] or m[3] or "00") if m else ""
        if not m or int(m[1]) > 23 or int(minute) > 59:
            raise ValueError(f"Khung giờ “{part}” không hợp lệ. Ví dụ: 08:00, 12:30, 20h")
        slots.append(f"{int(m[1]):02}:{minute}")
    return sorted(set(slots))


def caption_for(template: str, title: str, hashtags: str, source_url: str) -> str:
    text = re.sub(r"\{(title|hashtags|sourceUrl)\}", lambda m: {"title": title, "hashtags": hashtags, "sourceUrl": source_url}[m[1]], template)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:5000]


def due_slots(slots: list[str], fired: dict, now: datetime) -> list[str]:
    """Khung giờ đã tới trong 30 phút qua và chưa chạy hôm nay. Tắt máy lâu hơn thì bỏ qua, không đăng bù."""
    today = now.date().isoformat()
    due = []
    for slot in slots:
        h, m = map(int, slot.split(":"))
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if at <= now < at + SLOT_GRACE and fired.get(slot) != today:
            due.append(slot)
    return due


def next_slot(slots: list[str], fired: dict, now: datetime) -> datetime | None:
    today = now.date().isoformat()
    times = []
    for slot in slots:
        h, m = map(int, slot.split(":"))
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if at + SLOT_GRACE <= now or fired.get(slot) == today:
            at += timedelta(days=1)
        times.append(at)
    return min(times) if times else None


def post_record(video_id: str, page: dict, posts: dict) -> tuple[str, dict | None]:
    """Đối chiếu cả Page ID đã xác minh: đổi vanity URL sang ID không làm đăng trùng."""
    key = f"{video_id}|{page['url']}"
    if key in posts:
        return key, posts[key]
    page_id = accounts.page_key(page)
    if page_id.isdigit():
        for old_key, post in posts.items():
            if old_key.startswith(video_id + "|") and str(post.get("page_id")) == page_id:
                return old_key, post
    return key, None


def pick_video(library: list[dict], pages: list[dict], posts: dict) -> dict | None:
    """Video tải về sớm nhất còn Page chưa đăng. Bỏ qua cặp đã đăng, đang cần kiểm tra, hoặc lỗi quá MAX_FAILS lần."""
    for video in sorted(library, key=lambda v: v["modified"]):
        if not video.get("id"):
            continue
        for page in pages:
            _, post = post_record(video["id"], page, posts)
            if not post or (post["state"] == "failed" and post.get("fails", 0) < MAX_FAILS):
                return video
    return None


class Store:
    def __init__(self, path: Path = STATE):
        self.path = path
        self.lock = threading.RLock()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data and "accounts" not in data:
            backup = path.with_name(path.stem + ".v8-backup.json")
            if not backup.exists():
                backup.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        self.data = accounts.migrate({**json.loads(json.dumps(DEFAULTS)), **data})

    def account(self, account_id=None):
        return accounts.account_for(self.data, account_id)

    def update_account(self, account_id, **values):
        with self.lock:
            self.account(account_id).update(values)
            self.save()

    def save(self):
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    def set_post(self, key: str, **values):
        with self.lock:
            self.data["posts"][key] = {**self.data["posts"].get(key, {}), **values}
            self.save()

    def add_download(self, record: dict):
        """Ghi một dòng lịch sử tải (giữ tối đa MAX_DOWNLOAD_HISTORY dòng gần nhất)."""
        with self.lock:
            self.data["downloads"] = ([record] + self.data.get("downloads", []))[:MAX_DOWNLOAD_HISTORY]
            self.save()


class Engine(threading.Thread):
    """Vòng lặp: quét kênh theo chu kỳ, tải video mới, tới khung giờ thì đăng một video lên mọi Page."""

    def __init__(self, store: Store, settings, emit):
        super().__init__(daemon=True)
        self.store = store
        self.settings = settings  # () -> (thư mục lưu, chiều cao tối đa)
        self.emit = emit  # (kind, payload) -> None, gọi từ luồng này
        self.commands: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.tools = None
        self.last_scan = 0.0
        self.busy = False
        self.current: str | None = None  # việc đang làm, để giao diện hiển thị
        self.current_account_id: str | None = None
        # Lần trước tắt app giữa chừng: đã bấm Đăng thì phải kiểm tra tay, chưa bấm thì cho thử lại.
        for post in store.data["posts"].values():
            if post.get("state") == "posting":
                post.update(state="uncertain", error="App bị tắt sau khi bấm Đăng. Kiểm tra Page.")
            elif post.get("state") == "preparing":
                post.update(state="failed", error="App bị tắt trước khi bấm Đăng.")
        store.save()

    def session(self, account):
        session = upload.Session(self.store.data["show_browser"], account["browser"], account["id"])
        try:
            status = account.get("account") or {}
            if not status.get("ok"):
                raise upload.AuthRequired("Kiểm tra/đăng nhập tài khoản trước.")
            session.assert_identity(status.get("id"))
            return session
        except Exception:
            session.close()
            raise

    def log(self, text: str):
        now = datetime.now()
        line = f"{now:%H:%M} {text}"
        self.emit("log", line)
        try:  # lưu nhật ký ra file theo ngày để mở lại app vẫn còn
            LOG_DIR.mkdir(exist_ok=True)
            with open(LOG_DIR / f"bot-{now:%Y-%m-%d}.txt", "a", encoding="utf-8") as f:
                f.write(f"{now:%H:%M:%S} {text}\n")
        except OSError:
            pass

    def run(self):
        while not self.stop_event.is_set():
            try:
                command = self.commands.get(timeout=20)
            except queue.Empty:
                command = ("tick",)
            try:
                self.busy = True
                self.handle(*command)
            except Exception as e:  # không để một lỗi làm chết vòng lặp
                self.log(f"Lỗi: {e}")
            finally:
                self.busy = False
                self.current = None
                self.current_account_id = None
                self.emit("changed", None)

    def handle(self, kind, *args):
        data = self.store.data
        if kind in ("login", "open_browser"):
            account = self.store.account(args[0])
            self.current_account_id = account["id"]
            self.current = "login"
            self.log(f"[{account['label']}] Đã mở Facebook: đăng nhập, xác minh nếu được hỏi, xong thì đóng cửa sổ.")
            upload.login_until_closed(kind=account["browser"], account_id=account["id"])
            return self.check_account(account["id"])
        if kind == "check_account":
            return self.check_account(args[0])
        if kind == "scan_pages":
            return self.scan_pages(args[0])
        if kind == "scan_now":
            return self.scan()
        if kind == "post_now":
            return self.post_slot(args[0], manual=True)
        if kind == "lookup":
            return self.lookup(*args)
        if kind == "read_now":
            return self.read(args[0])
        if kind != "tick":
            return
        for account in list(data["accounts"]):
            if self.stop_event.is_set():
                return
            if not (account.get("account") or {}).get("ok"):
                continue
            if not account["enabled"]:
                continue
            now = datetime.now()
            for slot in due_slots(account["slots"], account["fired"], now):
                with self.store.lock:
                    account["fired"][slot] = now.date().isoformat()
                    self.store.save()
                self.log(f"[{account['label']}] Tới khung giờ {slot}.")
                self.post_slot(account["id"])
        if any(a["enabled"] for a in data["accounts"]) and time.time() - self.last_scan >= data["scan_minutes"] * 60:
            self.scan()
        # Ưu tiên lịch đăng; mỗi vòng đọc một tài khoản để không chặn lịch của các tài khoản khác.
        for account in list(data["accounts"]):
            if self.stop_event.is_set():
                return
            if (account.get("account") or {}).get("ok") and account["reading"] and account["keywords"] \
                    and time.time() - account["last_read"] >= READ_EVERY:
                self.read(account["id"])
                break

    def ensure_tools(self):
        if self.tools is None:
            self.tools = crawl.ensure_tools(lambda m, f=None: self.emit("status", m + (f" {f:.0%}" if f else "")))
        return self.tools

    # ---------- tài khoản ----------
    def check_account(self, account_id):
        account = self.store.account(account_id)
        self.current_account_id = account_id
        self.current = "check"
        try:
            with upload.Session(self.store.data["show_browser"], account["browser"], account_id) as s:
                identity = s.account()
            previous_id = (account.get("account") or {}).get("id")
            if previous_id and previous_id != identity["id"]:
                raise upload.AuthRequired("Hồ sơ đã đăng nhập tài khoản khác. Thêm tài khoản mới để dùng phiên này.")
            self.store.update_account(account_id, account={**identity, "ok": True,
                                      "checked_at": datetime.now().isoformat(timespec="minutes")})
            self.log(f"[{account['label']}] Đã đăng nhập Facebook: {identity['name'] or identity['id']}.")
        except upload.AuthRequired as e:
            self.auth_failed(account_id, str(e) or "Facebook chưa đăng nhập hoặc đang yêu cầu xác minh.")

    def auth_failed(self, account_id, message):
        account = self.store.account(account_id)
        status = {**(account.get("account") or {}), "ok": False,
                  "checked_at": datetime.now().isoformat(timespec="minutes"), "error": message}
        self.store.update_account(account_id, account=status)
        self.log(f"[{account['label']}] {message} Bấm Đăng nhập Facebook.")

    def scan_pages(self, account_id):
        account = self.store.account(account_id)
        self.current, self.current_account_id = "pages", account_id
        try:
            with self.session(account) as s:
                pages = s.managed_pages()
            with self.store.lock:
                # Chỉ đối chiếu Page đã chọn, không tự đưa Page mới vào lịch đăng.
                wanted = {accounts.page_key(p) for p in account["pages"]}
                selected = [p for p in pages if accounts.page_key(p) in wanted]
                account.update(available_pages=pages, pages=selected,
                               pages_checked_at=datetime.now().isoformat(timespec="minutes"), pages_error=None)
                if not selected:
                    account["enabled"] = False
                self.store.save()
            self.log(f"[{account['label']}] Đã quét {len(pages)} Page quản lý. Chọn Page ở Lịch đăng.")
        except upload.AuthRequired as e:
            self.auth_failed(account_id, str(e) or "Facebook yêu cầu đăng nhập lại.")
        except Exception as e:
            self.store.update_account(account_id, pages_error=str(e)[:300])
            self.log(f"[{account['label']}] Quét Page lỗi: {e}")

    # ---------- đọc tin ----------
    def read(self, account_id):
        data = self.store.account(account_id)
        self.current_account_id = account_id
        if not data["keywords"]:
            return self.log("Chưa có từ khóa để đọc tin.")
        with self.store.lock:
            data["last_read"] = time.time()
            self.store.save()
        keyword = random.choice(data["keywords"])
        self.current = "read"
        self.log(f"Đọc tin theo từ khóa “{keyword}” (khoảng 1 phút)…")
        try:
            with self.session(data) as s:
                s.read_feed(keyword, self.stop_event.wait)
            self.log("Đã tìm và cuộn đọc một lượt.")
        except upload.AuthRequired as e:
            self.auth_failed(account_id, str(e) or "Facebook yêu cầu đăng nhập/xác minh. Dừng đọc tin.")

    # ---------- Module 1: cào + tải ----------
    def scan(self):
        self.last_scan = time.time()
        data = self.store.data
        if not data["channels"]:
            return
        self.current = "scan"
        tools = self.ensure_tools()
        output, height = self.settings()
        for channel in data["channels"]:
            try:
                item = crawl.resolve(channel)
                videos = []
                crawl.list_videos(item, tools, videos.append, self.stop_event.is_set)
            except Exception as e:
                self.log(f"Không quét được {channel}: {str(e)[:150]}")
                continue
            seen = set(data["seen"].get(item.url, []))
            first = item.url not in data["seen"]
            new = [v for v in videos if v["id"] not in seen]
            with self.store.lock:
                data["seen"][item.url] = sorted(seen | {v["id"] for v in videos})
                self.store.save()
            if first:
                self.log(f"Lấy mốc kênh {item.url}: {len(videos)} video cũ, chỉ tải video mới từ giờ.")
                continue
            for video in reversed(new):  # cũ trước, mới sau
                if self.stop_event.is_set():
                    return
                self.log(f"Video mới: {video['title'][:60]} — đang tải…")
                at = datetime.now().isoformat(timespec="minutes")
                try:
                    result = crawl.download(video["url"], output, height, tools, lambda f, s: None, self.stop_event.is_set)
                    skipped = result.get("skipped")
                    self.log("Tải xong." if not skipped else "Đã có trong thư mục.")
                    self.store.add_download({"at": at, "title": result.get("title") or video["title"],
                                             "channel": result.get("channel") or "", "url": video["url"],
                                             "file": result.get("file"), "status": "Đã có" if skipped else "Đã tải"})
                except Exception as e:
                    self.log(f"Tải lỗi: {str(e)[:150]}")
                    self.store.add_download({"at": at, "title": video["title"], "channel": "", "url": video["url"],
                                             "file": None, "status": f"Lỗi: {str(e)[:120]}"})
        self.emit("library", None)

    # ---------- Module 2 + 3: render rồi đăng ----------
    def post_slot(self, account_id, manual=False):
        with self.store.lock:
            account = copy.deepcopy(self.store.account(account_id))
            data = {**self.store.data, **account}
        self.current_account_id = account_id
        if not (account.get("account") or {}).get("ok"):
            return self.log(f"[{account['label']}] Kiểm tra/đăng nhập Facebook trước khi đăng.")
        pages = data["pages"]
        if not pages:
            return self.log("Chưa có Page để đăng.")
        output, _ = self.settings()
        video = pick_video(crawl.library(output), pages, data["posts"])
        if not video:
            return self.log("Không còn video nào chưa đăng trong Thư viện.")
        caption = caption_for(data["caption"], video["title"], data["hashtags"], video.get("url") or "")
        self.current = "post"
        self.log(f"[{account['label']}] Đăng “{video['title'][:60]}” lên {len(pages)} Page{' (thử ngay)' if manual else ''}.")

        # Module 2 — render (nếu bật): reframe một lần, dùng cho mọi Page.
        upload_file = video["file"]
        rendered = None
        if render.available(data):
            try:
                upload_file = render.render(video["file"], data, self.stop_event.is_set, self.log)
                rendered = upload_file if upload_file != video["file"] else None
            except Exception as e:
                self.log(f"Render lỗi: {str(e)[:150]}. Đăng bản gốc.")

        try:
            session = self.session(account)
        except upload.AuthRequired as e:
            return self.auth_failed(account_id, str(e))
        except Exception as e:
            return self.log(f"Không mở được trình duyệt: {e}")
        try:
            for page in pages:
                key, post = post_record(video["id"], page, data["posts"])
                if post and (post["state"] in ("posted", "uncertain", "posting") or post.get("fails", 0) >= MAX_FAILS):
                    continue
                self.store.set_post(key, state="preparing", title=video["title"], page=page["name"],
                                    at=datetime.now().isoformat(timespec="minutes"), error=None,
                                    file=video["file"], rendered=rendered, account_id=account_id,
                                    account_label=account["label"], page_url=page["url"], caption=caption)
                self.emit("changed", None)
                try:
                    page_id = session.switch_page(page)
                    # Ghi "đang gửi" bền vững trước khi bấm: mất điện/treo sau đó sẽ thành Cần kiểm tra, không đăng lại.
                    url = session.publish(upload_file, caption, page, page_id,
                                          lambda: self.store.set_post(key, state="posting", page_id=page_id), self.log)
                    self.store.set_post(key, state="posted", url=url, error=None)
                    self.log(f"Đã đăng lên {page['name']}: {url}")
                except upload.AuthRequired:
                    state = "uncertain" if data["posts"][key]["state"] == "posting" else "failed"
                    self.store.set_post(key, state=state, error="Facebook yêu cầu đăng nhập/xác minh lại.")
                    self.auth_failed(account_id, "Facebook yêu cầu đăng nhập lại. Dừng đăng.")
                    return
                except upload.Uncertain as e:
                    self.store.set_post(key, state="uncertain", error=str(e))
                    self.log(f"{page['name']}: {e}")
                except Exception as e:
                    if data["posts"][key]["state"] == "posting":
                        self.store.set_post(key, state="uncertain", error=f"Lỗi sau khi bấm Đăng: {str(e)[:200]}")
                    else:
                        fails = data["posts"][key].get("fails", 0) + 1
                        self.store.set_post(key, state="failed", fails=fails, error=str(e)[:300])
                    self.log(f"{page['name']}: {str(e)[:200]}")
                self.emit("changed", None)
        finally:
            session.close()

    def lookup(self, key: str):
        """Kiểm tra lại bài Cần kiểm tra trên Page (chỉ đọc)."""
        post = self.store.data["posts"].get(key)
        if not post:
            return
        account = self.store.account(post.get("account_id") or "default")
        page = next((p for p in account["pages"] + account["available_pages"] if p["url"] == key.split("|", 1)[1]), None)
        if not page and post.get("page_url"):
            page = {"name": post["page"], "url": post["page_url"]}
        if not page:
            raise ValueError("Page không còn trong tài khoản đã đăng bài.")
        self.current_account_id = account["id"]
        self.current = "lookup"
        video = next((v for v in crawl.library(self.settings()[0]) if v["id"] == key.split("|")[0]), None)
        caption = post.get("caption") or caption_for(account["caption"], post.get("title") or "", account["hashtags"], (video or {}).get("url") or "")
        with self.session(account) as s:
            page_id = s.switch_page(page)
            url = s.lookup(page, page_id, caption)
        if url:
            self.store.set_post(key, state="posted", url=url, error=None)
            self.log(f"Tìm thấy bài trên {page['name']}: {url}")
        else:
            self.log(f"Chưa thấy bài trên {page['name']}. Mở Page kiểm tra bằng mắt.")
