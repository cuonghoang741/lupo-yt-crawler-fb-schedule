"""Giao diện web (pywebview) cho tool YouTube → Facebook.

Giữ nguyên 3 module (crawl / render / upload) và bộ điều phối automation.py; chỉ thay
lớp giao diện Tkinter bằng một trang web nhỏ chạy trong cửa sổ pywebview. Trang web nói
chuyện với Python qua HTTP loopback có token (giống Frame Preview): POST /api/state lấy
toàn bộ dữ liệu để vẽ, POST /api/action để thực hiện thao tác.
"""
from __future__ import annotations

import json
import copy
import hashlib
import os
import queue
import secrets
import shutil
import sys
import threading
import uuid
from collections import deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import automation
import crawl
import fbpost
import render as render_mod
import ytcore
import accounts
from youtube_auth import YouTubeAuth

ROOT = ytcore.app_dir()
# webui.html nằm cạnh file nguồn, hoặc trong gói khi đóng .exe bằng PyInstaller.
HTML_FILE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "webui.html"
SETTINGS = ROOT / "settings.json"
QUALITIES = {"1080p": 1080, "720p": 720, "480p": 480, "360p": 360}
STATES = {"posted": "Đã đăng", "uncertain": "Cần kiểm tra", "posting": "Đang đăng",
          "preparing": "Đang chuẩn bị", "failed": "Lỗi"}
ACTIVITY = {"login": "Đang chờ đăng nhập Facebook…", "check": "Đang kiểm tra tài khoản…",
            "scan": "Đang quét kênh YouTube…", "post": "Đang đăng bài…", "read": "Đang đọc tin…",
            "lookup": "Đang tìm bài trên Page…", "pages": "Đang quét Page quản lý…"}


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Api:
    """Toàn bộ trạng thái + thao tác, dùng chung cho trang web."""

    def __init__(self, store=None, start_engine=True):
        s = load_settings()
        self.output = s.get("output") or str(Path.home() / "Videos" / "YouTube")
        self.quality = s.get("quality") if s.get("quality") in QUALITIES else "1080p"
        self.logs: deque[str] = deque(maxlen=400)
        self.store = store or automation.Store()
        self.engine = automation.Engine(self.store, self._settings, self._emit)
        self.dialog = None  # main() gán hộp thoại chọn file của pywebview
        self.tools = None
        self.queue_file = self.store.path.with_name("download-queue.json")
        self.youtube = YouTubeAuth(self.store.path.parent / "youtube-session")
        self.jobs: list[dict] = []
        self.dl_paused, self.dl_error = False, ""
        self.dl_lock = threading.RLock()
        self._load_queue()
        self.thumb_key = secrets.token_hex(24)
        self.thumbnails = {}
        self.dl_stop = threading.Event()
        self.dl_thread: threading.Thread | None = None
        self.render_job = {"status": "idle", "title": "", "output": "", "error": ""}
        if start_engine:
            self.engine.start()
            if any(j["status"] == "Chờ" for j in self.jobs) and not self.dl_paused:
                self._ensure_worker()

    # ---------- nền ----------
    def _settings(self):
        return (Path(self.output), QUALITIES[self.quality])

    def _emit(self, kind, value):
        if kind == "log":
            self.logs.append(value)

    def save_settings(self):
        try:
            SETTINGS.write_text(json.dumps({"output": self.output, "quality": self.quality}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _update(self, **values):
        with self.store.lock:
            self.store.data.update(values)
            self.store.save()

    def _account(self, req):
        return self.store.account(req.get("account_id"))

    def _update_account(self, req, **values):
        self.store.update_account(self._account(req)["id"], **values)

    def _queue(self, name, req):
        self.engine.commands.put((name, self._account(req)["id"]))

    def _load_queue(self):
        try:
            data = json.loads(self.queue_file.read_text("utf-8"))
            for j in data.get("jobs", []):
                if not isinstance(j, dict) or not j.get("id") or j.get("kind") not in ("video", "channel"):
                    continue
                try:
                    ytcore.youtube_input(j.get("url", ""))
                except ValueError:
                    continue
                self.jobs.append({**j, "status": "Chờ" if j.get("status") == "Đang chạy" else j.get("status", "Chờ")})
            self.dl_paused, self.dl_error = bool(data.get("paused")), str(data.get("error") or "")
        except (OSError, ValueError, TypeError):
            pass

    def _save_queue(self):
        with self.dl_lock:
            tmp = self.queue_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"jobs": self.jobs, "paused": self.dl_paused, "error": self.dl_error},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.queue_file)

    def _thumbnail(self, path):
        if not path:
            return None
        token = hashlib.sha256((self.thumb_key + path).encode()).hexdigest()
        self.thumbnails[token] = path
        return "/thumbnails/" + token

    # ---------- dữ liệu cho giao diện ----------
    def _video_status(self, video, d):
        if not d["pages"] or not video.get("id"):
            return "Chờ đăng", "wait"
        states = [(automation.post_record(video["id"], p, d["posts"])[1] or {}).get("state") for p in d["pages"]]
        posted = states.count("posted")
        if "uncertain" in states:
            return "Cần kiểm tra", "warn"
        if posted == len(states):
            return "Đã đăng", "ok"
        if posted:
            return f"Đã đăng {posted}/{len(states)} Page", "wait"
        return "Chờ đăng", "wait"

    def _steps(self, d, library):
        return [
            {"key": "facebook", "title": "Đăng nhập Facebook", "desc": "Đăng nhập một lần bằng tài khoản quản lý Page.",
             "done": bool((d.get("account") or {}).get("ok"))},
            {"key": "schedule", "title": "Chọn Page sẽ đăng", "desc": "Quét Page tại Tài khoản & Page, rồi chọn ở Lịch đăng.",
             "done": bool(d["pages"])},
            {"key": "download", "title": "Tải video về Kho", "desc": "Dán link ở Tải thủ công để tải video về máy.",
             "done": bool(library)},
            {"key": "schedule", "title": "Chọn giờ đăng & nội dung", "desc": "Mặc định 08:00, 12:00, 20:00.",
             "done": bool(d.get("schedule_reviewed") or d["enabled"])},
            {"key": "overview", "title": "Bật tự động", "desc": "Tool tự đăng video trong Kho đúng giờ.",
             "done": bool(d["enabled"])},
        ]

    def snapshot(self):
        with self.store.lock:
            raw = copy.deepcopy(self.store.data)
            selected = accounts.account_for(raw)
            d = {**raw, **selected}
        library = crawl.library(Path(self.output))
        next_video = automation.pick_video(library, d["pages"], d["posts"]) if d["pages"] else None
        dl_map = {x["file"]: x.get("at", "") for x in d.get("downloads", []) if x.get("file")}
        rendered = {}  # file gốc -> đường dẫn bản render đã có cạnh nó
        videos = []
        waiting = 0
        for v in library:
            text, tag = self._video_status(v, d)
            is_next = next_video and v["id"] == next_video["id"]
            if tag == "wait":
                waiting += 1
            rpath = Path(v["file"]).parent / render_mod.RENDER_SUBDIR / (Path(v["file"]).stem + ".mp4")
            videos.append({"id": v.get("id"), "title": v["title"], "channel": v["channel"],
                           "duration": ytcore.human_duration(v["duration"]), "size": ytcore.human_size(v["size"]),
                           "file": v["file"], "url": v.get("url"), "at": (dl_map.get(v["file"], "")).replace("T", " "),
                           "rendered": str(rpath) if rpath.is_file() else "",
                           "thumbnail": self._thumbnail(v.get("thumbnail")),
                           "post": "Đăng tiếp theo" if is_next else text, "tag": "next" if is_next else tag})
        now = datetime.now()
        at = automation.next_slot(d["slots"], d["fired"], now) if d["enabled"] else None
        steps = self._steps(d, library)
        posts = sorted(d["posts"].items(), key=lambda kv: kv[1].get("at") or "", reverse=True)
        return {
            "output": self.output, "quality": self.quality,
            "enabled": d["enabled"], "busy": self.engine.busy,
            "activity": ACTIVITY.get(self.engine.current or ""),
            "activity_account_id": self.engine.current_account_id,
            "selected_account_id": selected["id"], "account_label": selected["label"],
            "accounts": [{"id": a["id"], "label": a["label"], "browser": a["browser"],
                          "ok": bool((a.get("account") or {}).get("ok")), "enabled": a["enabled"],
                          "page_count": len(a["pages"])} for a in raw["accounts"]],
            "enabled_accounts": sum(bool(a["enabled"]) for a in raw["accounts"]),
            "account": d.get("account"), "pages": d["pages"], "channels": d["channels"],
            "available_pages": d["available_pages"], "pages_error": d.get("pages_error"),
            "pages_checked_at": d.get("pages_checked_at"),
            "browser": fbpost.normalize_browser(d.get("browser")),
            "browsers": [{"id": k, "label": v["label"]} for k, v in fbpost.BROWSERS.items()],
            "seen": {k: len(v) for k, v in d["seen"].items()},
            "slots": d["slots"], "caption": d["caption"], "hashtags": d["hashtags"],
            "schedule_reviewed": d.get("schedule_reviewed", False),
            "render": {"enabled": d["render_enabled"], "ratio": d["render_ratio"], "fit": d["render_fit"],
                       "frame_dir": d["frame_dir"], "found": str(render_mod.frame_dir(d["frame_dir"]) or "")},
            "reading": d["reading"], "keywords": d["keywords"], "show_browser": d["show_browser"],
            "steps": steps,
            "next_slot": f"{at:%H:%M · %d/%m}" if at else None,
            "next_video": next_video["title"] if next_video else None,
            "library": videos, "waiting": waiting,
            "failed_downloads": [x for x in d.get("downloads", []) if str(x.get("status", "")).startswith("Lỗi")][:50],
            "render_job": self.render_job,
            "jobs": copy.deepcopy(self.jobs),
            "youtube": self.youtube.snapshot(), "download_paused": self.dl_paused, "download_error": self.dl_error,
            "posts": [{"key": k, "at": (p.get("at") or "").replace("T", " "), "title": p.get("title", ""),
                       "page": p.get("page", ""), "state": p.get("state", ""), "state_text": STATES.get(p.get("state"), p.get("state", "")),
                       "account_label": p.get("account_label") or next((a["label"] for a in raw["accounts"] if a["id"] == p.get("account_id")), "Tài khoản cũ"),
                       "url": p.get("url"), "error": p.get("error"), "file": p.get("rendered") or p.get("file")}
                      for k, p in posts[:300]],
            "posted_count": sum(p.get("state") == "posted" for p in d["posts"].values()),
            "check_count": sum(p.get("state") == "uncertain" for p in d["posts"].values()),
            "log": list(self.logs)[-200:],
        }

    # ---------- thao tác ----------
    def action(self, req):
        name = req.get("action")
        fn = getattr(self, "do_" + name, None) if name else None
        if not fn:
            raise ValueError("Thao tác không hợp lệ.")
        result = fn(req)
        return result if isinstance(result, dict) else {"ok": True}

    def do_set_output(self, req):
        if self.dialog:
            picked = self.dialog("folder")
            if picked:
                self.output = picked
                self.save_settings()
        return {"ok": True}

    def do_set_quality(self, req):
        if req.get("quality") in QUALITIES:
            self.quality = req["quality"]
            self.save_settings()
        return {"ok": True}

    def do_open(self, req):
        path = req.get("path")
        if isinstance(path, str) and accounts.facebook_url(path):
            import webbrowser
            webbrowser.open(path)
            return {"ok": True}
        if path and Path(path).exists():
            if os.name == "nt":
                os.startfile(path)  # noqa: S606
            else:
                import subprocess
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", path], check=False)
        return {"ok": True}

    def do_open_folder(self, req):
        path = req.get("path") or self.output
        Path(path if Path(path).is_dir() else Path(path).parent).mkdir(parents=True, exist_ok=True)
        return self.do_open({"path": path if Path(path).is_dir() else str(Path(path).parent)})

    # Facebook
    def do_select_account(self, req):
        account = self._account(req)
        self._update(selected_account_id=account["id"])
        return {"ok": True}

    def do_add_account(self, req):
        label = (req.get("label") or "").strip()
        if not label or len(label) > 100:
            raise ValueError("Nhập tên tài khoản, tối đa 100 ký tự.")
        with self.store.lock:
            if any(a["label"].casefold() == label.casefold() for a in self.store.data["accounts"]):
                raise ValueError("Tên tài khoản này đã có. Chọn tên khác để dễ phân biệt.")
            account = accounts.new_account(label, fbpost.normalize_browser(req.get("browser")))
            self.store.data["accounts"].append(account)
            self._update(selected_account_id=account["id"])
        return {"ok": True, "account_id": account["id"]}

    def do_remove_account(self, req):
        with self.store.lock:
            account = self._account(req)
            if len(self.store.data["accounts"]) <= 1:
                raise ValueError("Cần giữ ít nhất một tài khoản.")
            if account["enabled"] or self.engine.busy or not self.engine.commands.empty():
                raise ValueError("Tắt tự động và đợi các thao tác đang chạy/chờ xong rồi xóa tài khoản.")
            self._update(accounts=[a for a in self.store.data["accounts"] if a["id"] != account["id"]])
            if self.store.data["selected_account_id"] == account["id"]:
                self._update(selected_account_id=self.store.data["accounts"][0]["id"])
        return {"ok": True}  # giữ hồ sơ trên đĩa và lịch sử đăng, không xóa dữ liệu đăng nhập

    def do_set_browser(self, req):
        kind = fbpost.normalize_browser(req.get("browser"))
        account = self._account(req)
        if account["browser"] == kind:
            return {"ok": True}
        if account["enabled"] or self.engine.busy or not self.engine.commands.empty():
            raise ValueError("Tắt tự động và đợi thao tác hiện tại xong trước khi đổi trình duyệt.")
        status = {**(account.get("account") or {}), "ok": False}
        self._update_account(req, browser=kind, account=status)
        return {"ok": True}

    def do_login(self, req):
        if req.get("browser"):
            self.do_set_browser(req)
        self._queue("login", req)
        return {"ok": True}

    def do_open_browser(self, req):
        self._queue("open_browser", req)
        return {"ok": True}

    def do_check_account(self, req):
        self._queue("check_account", req)
        return {"ok": True}

    def do_scan_pages(self, req):
        self._queue("scan_pages", req)
        return {"ok": True}

    def do_remove_page(self, req):
        url = req.get("url")
        account = self._account(req)
        pages = [p for p in account["pages"] if p["url"] != url]
        if account["enabled"] and not pages:
            raise ValueError("Đang bật tự động nên cần giữ ít nhất một Page. Tắt tự động trước.")
        self._update_account(req, pages=pages)
        return {"ok": True}

    # Kênh
    def do_add_channel(self, req):
        item = crawl.resolve(req.get("url") or "")
        if item.kind != "channel":
            raise ValueError("Đây là link video. Dán link kênh (có @tên hoặc /channel/…).")
        if item.url in self.store.data["channels"]:
            raise ValueError("Kênh này đã có trong danh sách.")
        self._update(channels=self.store.data["channels"] + [item.url])
        self.engine.commands.put(("scan_now",))
        return {"ok": True}

    def do_remove_channel(self, req):
        self._update(channels=[c for c in self.store.data["channels"] if c != req.get("url")])
        return {"ok": True}

    def do_scan_now(self, req):
        self.engine.commands.put(("scan_now",))
        return {"ok": True}

    # Lịch đăng
    def do_save_schedule(self, req):
        slots = automation.parse_slots(req.get("slots") or "")
        if not slots:
            raise ValueError("Cần ít nhất một giờ đăng.")
        caption = (req.get("caption") or "").strip()
        if not caption:
            raise ValueError("Nội dung bài không được trống. Dùng {title} để lấy tiêu đề video.")
        account = self._account(req)
        pages = accounts.selected_pages(account, req.get("page_urls") or [])
        if not pages:
            raise ValueError("Chọn ít nhất một Page quản lý của tài khoản này.")
        self._update_account(req, slots=slots, caption=caption, hashtags=(req.get("hashtags") or "").strip(),
                             pages=pages, schedule_reviewed=True)
        return {"ok": True, "slots": slots}

    def do_preview_caption(self, req):
        d = {**self.store.data, **self._account(req)}
        library = crawl.library(Path(self.output))
        nv = automation.pick_video(library, d["pages"], d["posts"]) if d["pages"] else None
        title = nv["title"] if nv else "Tiêu đề video mẫu"
        url = (nv or {}).get("url") or "https://www.youtube.com/watch?v=…"
        return {"preview": automation.caption_for(req.get("caption") or "", title, (req.get("hashtags") or "").strip(), url)}

    # Tự động
    def do_toggle_enabled(self, req):
        d = self._account(req)
        if d["enabled"]:
            self._update_account(req, enabled=False)
            return {"ok": True}
        if not d["pages"]:
            raise ValueError("Thêm ít nhất một Page trước.")
        if not d["slots"]:
            raise ValueError("Chọn ít nhất một giờ đăng trước.")
        if not (d.get("account") or {}).get("ok"):
            raise ValueError("Đăng nhập và kiểm tra tài khoản Facebook trước.")
        self._update_account(req, enabled=True)
        if self.store.data["channels"]:
            self.engine.commands.put(("scan_now",))
        return {"ok": True}

    def do_post_now(self, req):
        if not self._account(req)["pages"]:
            raise ValueError("Thêm Page trước.")
        self._queue("post_now", req)
        return {"ok": True}

    def do_lookup(self, req):
        self.engine.commands.put(("lookup", req.get("key")))
        return {"ok": True}

    def do_mark_posted(self, req):
        url = (req.get("url") or "").strip()
        if not accounts.facebook_url(url):
            raise ValueError("Link phải là link bài Facebook (https://…facebook.com/…).")
        self.store.set_post(req.get("key"), state="posted", url=url, error=None)
        return {"ok": True}

    def do_allow_retry(self, req):
        post = self.store.data["posts"].get(req.get("key"))
        if not post or post.get("state") not in ("uncertain", "failed"):
            raise ValueError("Chỉ dùng cho bài Cần kiểm tra hoặc Lỗi.")
        self.store.set_post(req.get("key"), state="failed", fails=0, error="Chờ đăng lại ở khung giờ tới.")
        return {"ok": True}

    # Cài đặt render + nâng cao
    def do_save_render(self, req):
        fit = req.get("fit") if req.get("fit") in ("blur", "crop", "pad") else "blur"
        self._update(render_enabled=bool(req.get("enabled")), render_ratio=req.get("ratio") or "9:16",
                     render_fit=fit, frame_dir=(req.get("frame_dir") or "").strip())
        return {"ok": True, "found": str(render_mod.frame_dir((req.get("frame_dir") or "").strip()) or "")}

    def do_pick_frame_dir(self, req):
        if self.dialog:
            picked = self.dialog("folder")
            if picked:
                self._update(frame_dir=picked)
        return {"ok": True}

    def do_save_advanced(self, req):
        keywords = automation.parse_keywords(req.get("keywords") or "")
        if req.get("reading") and not keywords:
            raise ValueError("Cần ít nhất một từ khóa để bật đọc tin.")
        self._update_account(req, keywords=keywords, reading=bool(req.get("reading")))
        self._update(show_browser=bool(req.get("show_browser")))
        return {"ok": True}

    def do_read_now(self, req):
        self._queue("read_now", req)
        return {"ok": True}

    # Kho video
    def do_delete_video(self, req):
        for v in crawl.library(Path(self.output)):
            if v["file"] == req.get("file"):
                ytcore.delete_video(v, Path(self.output))
                break
        return {"ok": True}

    def do_import_videos(self, req):
        """Thêm video có sẵn trên máy vào Kho để lên lịch đăng."""
        if not self.dialog:
            raise ValueError("Không mở được hộp thoại chọn file.")
        files = self.dialog("files")
        if not files:
            return {"ok": True, "added": 0}
        folder = Path(self.output) / "Video tải lên"
        folder.mkdir(parents=True, exist_ok=True)
        added = 0
        for raw in files:
            src = Path(raw)
            if src.suffix.lower() not in ytcore.EXTS or not src.is_file():
                continue
            vid = "local-" + uuid.uuid4().hex[:11]
            stem = ytcore.safe_stem(src.stem)[:120] + f" [{vid}]"
            dest = folder / (stem + src.suffix.lower())
            shutil.copyfile(src, dest)
            info = {"id": vid, "title": src.stem, "channel": "Video tải lên", "webpage_url": None,
                    "duration": None, "width": None, "height": None, "upload_date": None}
            dest.with_name(stem + ".info.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
            added += 1
        self.logs.append(f"{datetime.now():%H:%M} Đã thêm {added} video từ máy vào Kho.")
        return {"ok": True, "added": added}

    # Render thủ công (chọn video render lại)
    def do_render_video(self, req):
        if self.render_job["status"] == "running":
            raise ValueError("Đang render một video khác, đợi xong đã.")
        file = req.get("file")
        if not file or not Path(file).exists():
            raise ValueError("Chọn một video trong Kho trước.")
        frame = render_mod.frame_dir(self.store.data["frame_dir"])
        if not frame:
            raise ValueError("Chưa tìm thấy Frame Preview. Vào Cài đặt chọn thư mục chứa render_cli.py.")
        settings = {"render_enabled": True, "render_ratio": req.get("ratio") or "9:16",
                    "render_fit": req.get("fit") if req.get("fit") in ("blur", "crop", "pad") else "blur",
                    "frame_dir": self.store.data["frame_dir"]}
        self.render_job = {"status": "running", "title": Path(file).name, "output": "", "error": "",
                           "ratio": settings["render_ratio"], "fit": settings["render_fit"]}

        def work():
            try:
                out = render_mod.render(file, settings, lambda: False, lambda m: self.logs.append(f"{datetime.now():%H:%M} {m}"))
                if out and out != file and Path(out).exists():
                    self.render_job.update(status="done", output=out)
                else:
                    self.render_job.update(status="error", error="Render không ra file (xem nhật ký).")
            except Exception as e:
                self.render_job.update(status="error", error=str(e)[:200])

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    # Tải thủ công
    def do_youtube_login(self, req):
        self.youtube.login(req.get("browser") or "chrome")
        self.do_pause_downloads({})
        return {"ok": True}

    def do_youtube_mode(self, req):
        self.youtube.set_mode(req.get("mode"))
        return {"ok": True}

    def do_youtube_import_cookie(self, req):
        if not self.dialog:
            raise ValueError("Không mở được hộp thoại chọn file.")
        picked = self.dialog("cookie")
        if picked:
            self.youtube.import_file(picked)
        return {"ok": True}

    def do_youtube_forget(self, req):
        self.youtube.forget()
        return {"ok": True}

    def do_import_links(self, req):
        if not self.dialog:
            raise ValueError("Không mở được hộp thoại chọn file.")
        picked = self.dialog("links")
        if not picked:
            return {"ok": True, "added": 0}
        path = Path(picked)
        if path.stat().st_size > 1_000_000:
            raise ValueError("File tối đa 1 MB.")
        return self.do_start_download({"text": path.read_text("utf-8-sig")})

    def do_download_template(self, req):
        if not self.dialog:
            raise ValueError("Không mở được hộp thoại lưu file.")
        picked = self.dialog("template")
        if picked:
            Path(picked).write_text("url\nhttps://www.youtube.com/@ChosenByHeavens\n", encoding="utf-8-sig")
        return {"ok": True}

    def do_start_download(self, req):
        try:
            items = ytcore.parse_import(req.get("text") or "")
        except ValueError as e:
            raise ValueError(str(e))
        added = 0
        with self.dl_lock:
            for it in items:
                existing = next((j for j in self.jobs if j["url"] == it.url and j["status"] not in ("Xong", "Đã có")), None)
                if existing:
                    if existing["status"] in ("Lỗi", "Chờ xác minh"):
                        existing.update(status="Chờ", progress="")
                    continue
                self.jobs.append({"id": uuid.uuid4().hex, "url": it.url, "kind": it.kind,
                                  "title": it.url if it.kind == "video" else f"Kênh: {it.url}",
                                  "channel": "", "status": "Chờ", "progress": ""})
                added += 1
            self._save_queue()
        self._ensure_worker()
        return {"ok": True, "added": added}

    def do_retry_downloads(self, req):
        if self.youtube.busy:
            raise ValueError("Đóng cửa sổ YouTube sau khi đăng nhập rồi bấm Tiếp tục.")
        with self.dl_lock:
            for j in self.jobs:
                if j["status"] in ("Lỗi", "Chờ xác minh") and (not req.get("id") or req["id"] == j["id"]):
                    j.update(status="Chờ", progress="")
            self.dl_paused, self.dl_error = False, ""
            self._save_queue()
        self._ensure_worker()
        return {"ok": True}

    def do_pause_downloads(self, req):
        with self.dl_lock:
            self.dl_paused, self.dl_error = True, "Đã tạm dừng tải. Bấm Tiếp tục khi sẵn sàng."
            self.dl_stop.set()
            self._save_queue()
        return {"ok": True}

    def do_clear_done(self, req):
        with self.dl_lock:
            self.jobs = [j for j in self.jobs if j["status"] not in ("Xong", "Đã có")]
            self._save_queue()
        return {"ok": True}

    def _ensure_worker(self):
        with self.dl_lock:
            if self.dl_paused:
                return
            self.dl_stop.clear()
            if self.dl_thread and self.dl_thread.is_alive():
                return
            self.dl_thread = threading.Thread(target=self._download_worker, daemon=True)
            self.dl_thread.start()

    def _download_worker(self):
        try:
            if self.tools is None:
                self.tools = crawl.ensure_tools(lambda m, f=None: self.logs.append(m))
            output, height = self._settings()
            while not self.dl_stop.is_set() and not self.dl_paused:
                with self.dl_lock:
                    job = next((j for j in self.jobs if j["status"] == "Chờ" and j["kind"] == "channel"), None) \
                        or next((j for j in self.jobs if j["status"] == "Chờ"), None)
                    if not job:
                        break
                    job["status"] = "Đang chạy"
                    self._save_queue()
                if job["kind"] == "channel":
                    self._dl_channel(job, output, height)
                else:
                    self._dl_video(job, output, height)
        except Exception as e:
            self.dl_paused, self.dl_error = True, "Không chuẩn bị được công cụ tải. Kiểm tra mạng rồi bấm Tiếp tục."
            self.logs.append(self.dl_error)
        finally:
            with self.dl_lock:
                self._save_queue()
                self.dl_thread = None
                if not self.dl_stop.is_set() and not self.dl_paused and any(j["status"] == "Chờ" for j in self.jobs):
                    self._ensure_worker()

    def _job_error(self, job, error):
        with self.dl_lock:
            if isinstance(error, ytcore.Cancelled):
                job.update(status="Chờ", progress="")
            elif isinstance(error, (ytcore.YoutubeAuthRequired, ytcore.YoutubeRateLimited)):
                self.dl_paused, self.dl_error = True, str(error)
                job.update(status="Chờ xác minh" if isinstance(error, ytcore.YoutubeAuthRequired) else "Lỗi", progress=str(error))
            else:
                job.update(status="Lỗi", progress=str(error)[:300])
            self._save_queue()

    def _dl_channel(self, job, output, height):
        count = 0
        def on_video(v):
            nonlocal count
            count += 1
            with self.dl_lock:
                if not any(j["url"] == v["url"] for j in self.jobs):
                    self.jobs.append({"id": uuid.uuid4().hex, "url": v["url"], "kind": "video",
                                      "title": v["title"], "channel": v["channel"], "status": "Chờ", "progress": ""})
                if count % 50 == 0:
                    self._save_queue()
        try:
            crawl.list_videos(crawl.resolve(job["url"]), self.tools, on_video, self.dl_stop.is_set)
        except Exception as e:
            self._job_error(job, e)
            return
        with self.dl_lock:
            job.update(status="Xong", progress=f"{count} video")
            self._save_queue()

    def _dl_video(self, job, output, height):
        def progress(fraction, speed):
            job["progress"] = f"{fraction:.0%}" if fraction is not None else ""
        try:
            result = crawl.download(job["url"], output, height, self.tools, progress, self.dl_stop.is_set)
        except Exception as e:
            self._job_error(job, e)
            if not isinstance(e, ytcore.Cancelled):
                self.store.add_download({"at": datetime.now().isoformat(timespec="minutes"), "title": job["title"],
                                         "channel": job.get("channel"), "url": job["url"], "status": "Lỗi: " + job["progress"]})
            return
        if result.get("skipped"):
            job.update(status="Đã có", progress="")
        else:
            job.update(status="Xong", progress="100%", title=result.get("title") or job["title"],
                       channel=result.get("channel") or "")
        self.store.add_download({"at": datetime.now().isoformat(timespec="minutes"),
                                 "title": result.get("title") or job["title"], "channel": result.get("channel") or "",
                                 "url": job["url"], "file": result.get("file"),
                                 "status": "Đã có" if result.get("skipped") else "Đã tải"})
        self._save_queue()

    def shutdown(self):
        self.dl_stop.set()
        self.engine.stop_event.set()
        self.youtube.stop.set()


# ---------- HTTP loopback có token (theo mẫu Frame Preview) ----------
class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, api):
        super().__init__(("127.0.0.1", 0), Handler)
        self.api = api
        self.token = secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(20)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    @property
    def url(self):
        return self.origin + "/#" + self.token


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, payload, typ="application/json; charset=utf-8"):
        try:
            return self._send(status, payload, typ)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return  # cửa sổ đã đóng hoặc trang vừa tải lại

    def _send(self, status, payload, typ):
        if not isinstance(payload, bytes):
            payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         f"default-src 'none'; script-src 'nonce-{self.server.nonce}'; style-src 'unsafe-inline'; "
                         f"connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def allowed(self):
        return self.headers.get("Host") == self.server.origin.removeprefix("http://") and self.client_address[0] == "127.0.0.1"

    def auth(self):
        return self.allowed() and secrets.compare_digest(self.headers.get("X-Token", ""), self.server.token) \
            and self.headers.get("Origin") == self.server.origin

    def do_GET(self):
        if not self.allowed():
            return self.send(403, {"error": "Yêu cầu trái phép."})
        if self.path == "/":
            html = HTML_FILE.read_text("utf-8").replace("__NONCE__", self.server.nonce)
            return self.send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if self.path.startswith("/thumbnails/"):
            path = self.server.api.thumbnails.get(self.path.removeprefix("/thumbnails/"))
            if path:
                p = Path(path)
                types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
                if p.is_file() and p.suffix.lower() in types and p.stat().st_size <= 5_000_000:
                    return self.send(200, p.read_bytes(), types[p.suffix.lower()])
            return self.send(404, {"error": "Không có thumbnail."})
        return self.send(404, {"error": "Không có tài nguyên."})

    def do_POST(self):
        if not self.auth():
            return self.send(403, {"error": "Phiên không hợp lệ."})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if self.path == "/api/state":
                return self.send(200, self.server.api.snapshot())
            if self.path == "/api/action":
                return self.send(200, self.server.api.action(req))
            return self.send(404, {"error": "Không có API."})
        except Exception as e:
            return self.send(400, {"error": str(e)[:300]})


def main():
    data = ROOT / "logs"
    data.mkdir(exist_ok=True)
    try:
        import webview
    except ImportError:
        print("Thiếu pywebview. Chạy setup.bat để cài.")
        return
    api = Api()
    server = Server(api)
    for key in ("ALLOW_DOWNLOADS", "ALLOW_FILE_URLS", "OPEN_EXTERNAL_LINKS_IN_BROWSER"):
        webview.settings[key] = False
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    window = webview.create_window("YouTube → Facebook · v10", server.url, width=1180, height=800,
                                   min_size=(900, 600), background_color="#0F1115")

    def dialog(kind):
        if kind == "files":
            exts = ("Video (*.mp4;*.mkv;*.mov;*.webm;*.avi;*.m4v)",)
            return window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=exts) or []
        if kind in ("cookie", "links"):
            types = ("Cookie Netscape (*.txt)",) if kind == "cookie" else ("Danh sách link (*.csv;*.txt;*.tsv)",)
            picked = window.create_file_dialog(webview.FileDialog.OPEN, file_types=types)
            return picked[0] if picked else ""
        if kind == "template":
            picked = window.create_file_dialog(webview.FileDialog.SAVE, save_filename="youtube-template.csv", file_types=("CSV (*.csv)",))
            return (picked[0] if isinstance(picked, (tuple, list)) else picked) or ""
        value = window.create_file_dialog(webview.FileDialog.FOLDER)
        return value[0] if value else ""

    api.dialog = dialog
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        webview.start()
    finally:
        api.shutdown()


if __name__ == "__main__":
    main()
