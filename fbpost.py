"""Đăng video lên Page Facebook bằng trình duyệt trên máy (Playwright), dùng hồ sơ Chrome người dùng tự đăng nhập.

Chuyển từ scripts/facebook-bot/publish-ui.mjs của bản web. Không giả dấu vân tay, không vượt xác minh:
gặp trang đăng nhập/xác minh thì dừng và báo AUTH_REQUIRED.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import ytcore

BLOCKED = re.compile(r"^/(login|checkpoint|challenge|two_step_verification|recover|consent)(/|\.|$)")
POST_LINK = re.compile(r"/(posts|videos|reel)/[^/?#]+|/(permalink|story)\.php$")


class AuthRequired(Exception):
    pass


class Uncertain(Exception):
    """Đã bấm Đăng nhưng chưa xác nhận được bài: không được tự đăng lại."""


def profile_dir() -> Path:
    d = ytcore.app_dir() / "fb-profile"
    d.mkdir(exist_ok=True)
    return d


def browser() -> tuple[str, str] | None:
    """(kênh Playwright, đường dẫn exe). Ưu tiên Chrome, không có thì Edge (luôn có trên Windows 10/11)."""
    if os.name == "nt":
        roots = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for channel, rel in (("chrome", r"Google\Chrome\Application\chrome.exe"), ("msedge", r"Microsoft\Edge\Application\msedge.exe")):
            for root in roots:
                if root and Path(root, rel).exists():
                    return channel, str(Path(root, rel))
        return None
    if sys.platform == "darwin":
        app = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        return ("chrome", app) if Path(app).exists() else None
    exe = shutil.which("google-chrome")
    return ("chrome", exe) if exe else None


def login_until_closed(timeout_s: int = 15 * 60) -> None:
    """Mở cửa sổ Facebook bằng đúng hồ sơ bot dùng để đăng; chờ người dùng đăng nhập rồi tự đóng cửa sổ."""
    with Session(visible=True) as s:
        s.page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        closed = []
        s.context.on("close", lambda *_: closed.append(True))
        deadline = time.time() + timeout_s
        while not closed and time.time() < deadline:
            try:
                if not s.context.pages:
                    break
                s.context.pages[0].wait_for_timeout(1000)
            except Exception:
                break


class Session:
    """Một phiên trình duyệt dùng hồ sơ đã đăng nhập. Mặc định ẩn; visible=True để xem bot làm gì.

    Ẩn bằng cách đặt cửa sổ ra ngoài màn hình chứ không dùng headless: headless tự báo "HeadlessChrome"
    trong user agent, dễ bị Facebook bắt xác minh, mà bot không sửa dấu vân tay trình duyệt."""

    def __init__(self, visible: bool = False):
        from playwright.sync_api import sync_playwright

        found = browser()
        if not found:
            raise RuntimeError("Không tìm thấy Google Chrome hoặc Microsoft Edge trên máy.")
        self._pw = sync_playwright().start()
        try:
            self.context = self._pw.chromium.launch_persistent_context(
                str(profile_dir()), channel=found[0], headless=False,
                args=[] if visible else ["--window-position=-32000,-32000"], viewport={"width": 1366, "height": 900},
            )
        except Exception as e:
            self._pw.stop()
            if "ProcessSingleton" in str(e) or "already" in str(e).lower():
                raise RuntimeError("Cửa sổ đăng nhập Facebook còn mở. Đóng nó rồi thử lại.")
            raise
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(30_000)
        if not visible:
            try:  # macOS không cho đặt cửa sổ ngoài màn hình, nên thu nhỏ thêm
                cdp = self.context.new_cdp_session(self.page)
                window = cdp.send("Browser.getWindowForTarget")["windowId"]
                cdp.send("Browser.setWindowBounds", {"windowId": window, "bounds": {"windowState": "minimized"}})
            except Exception:
                pass

    @classmethod
    def wrap(cls, context, page) -> "Session":
        """Dùng một trình duyệt có sẵn (kiểm thử bằng trang giả lập, không mở Facebook thật)."""
        session = cls.__new__(cls)
        session._pw, session.context, session.page = None, context, page
        return session

    def close(self):
        if self._pw is None:
            return self.context.close()
        try:
            self.context.close()
        finally:
            self._pw.stop()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def cookie(self, name: str) -> str | None:
        return next((c["value"] for c in self.context.cookies("https://www.facebook.com") if c["name"] == name), None)

    # ---------- helpers ----------
    def check(self):
        url = urlparse(self.page.url)
        if not (url.hostname or "").endswith("facebook.com") or BLOCKED.match(url.path):
            raise AuthRequired()
        if self.page.query_selector('input[name="email"],input[name="pass"],form[action*="checkpoint"]'):
            raise AuthRequired()

    def goto(self, url: str):
        target = urlparse(url)
        if target.scheme != "https" or not (target.hostname or "").endswith("facebook.com"):
            raise ValueError("Link Facebook không hợp lệ.")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as e:
            if "Timeout" not in type(e).__name__ and "Timeout" not in str(e):
                raise
        self.check()

    def buttons(self, pattern: str, root: str = '[role="button"],button,a'):
        found = []
        for el in self.page.query_selector_all(root):
            try:
                data = el.evaluate("""el => ({
                    text: (el.getAttribute('aria-label') || el.innerText || '').trim().replace(/\\s+/g, ' '),
                    visible: !!(el.getBoundingClientRect().width && el.getBoundingClientRect().height),
                    disabled: el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true'})""")
            except Exception:
                continue
            if data["visible"] and not data["disabled"] and re.search(pattern, data["text"], re.I):
                found.append(el)
        return found

    def click(self, pattern: str, root: str = '[role="button"],button,a') -> bool:
        found = self.buttons(pattern, root)
        if not found:
            return False
        found[-1].click()
        return True

    # ---------- tài khoản ----------
    def account(self) -> dict:
        """Tên và ID tài khoản đang đăng nhập; AuthRequired nếu chưa đăng nhập hoặc đang bị xác minh."""
        user = self.cookie("c_user")
        if not user:
            raise AuthRequired()
        self.goto("https://www.facebook.com/me/")
        self.page.wait_for_selector('[role="main"]', timeout=20_000)
        self.check()
        title = self.page.title()
        match = re.match(r"^(?:\(\d+\)\s*)?(.+?)\s*\|\s*Facebook$", title)
        return {"id": user, "name": match.group(1) if match else None}

    # ---------- đọc tin ----------
    def read_feed(self, keyword: str, wait, rounds: int = 6, pause: float = 10) -> None:
        """Như bản web: tìm bài theo từ khóa rồi cuộn đọc 6 lần, mỗi lần cách 10 giây. Chỉ đọc, không bấm thích/bình luận.
        `wait(giây)` trả True nếu app đang tắt."""
        if not self.cookie("c_user"):
            raise AuthRequired()
        self.goto("https://www.facebook.com/search/posts/?q=" + quote(keyword))
        self.page.wait_for_selector('[role="main"]', timeout=30_000)
        self.check()
        for _ in range(rounds):
            if wait(pause):
                return
            self.check()
            self.page.evaluate("window.scrollBy(0, Math.round(window.innerHeight * 0.75))")
        self.check()

    # ---------- Page ----------
    def switch_page(self, page: dict) -> str:
        """Chuyển sang danh tính Page; trả về Page ID đã xác minh qua cookie i_user."""
        if not self.cookie("c_user"):
            raise AuthRequired()
        target = urlparse(page["url"])
        expected = (parse_qs(target.query).get("id") or [None])[0] or (
            target.path.strip("/") if re.fullmatch(r"/\d+/?", target.path) else None)
        self.goto(page["url"])
        active = self.cookie("i_user")
        if not (expected and active == expected):
            switch = r"^(Switch now|Chuyển ngay|Switch into Page|Chuyển sang Trang)$"
            profile = r"^(Your profile|Trang cá nhân của bạn|Tài khoản của bạn|Account|Tài khoản)$"
            for _ in range(25):
                if self.buttons(switch) or self.buttons(profile):
                    break
                time.sleep(1)
            if not self.click(switch):
                if not self.click(profile):
                    raise RuntimeError("Không mở được bộ chọn Page. Kiểm tra giao diện Facebook.")
                time.sleep(1)
                self.click(r"^(See all profiles|Xem tất cả trang cá nhân|See all Pages|Xem tất cả Trang)$")
                time.sleep(1.5)
                choices = self.buttons("^" + re.escape(page["name"]) + "$")
                if len(choices) != 1:
                    raise RuntimeError(f"Không tìm thấy đúng một Page tên “{page['name']}” trong tài khoản.")
                choices[0].click()
            for _ in range(30):
                time.sleep(0.5)
                self.check()
                active = self.cookie("i_user")
                if active and (not expected or active == expected):
                    break
            if not active or not active.isdigit() or (expected and active != expected):
                raise RuntimeError("Không xác minh được danh tính Page; dừng trước khi tải video.")
            self.goto(f"https://www.facebook.com/profile.php?id={active}")
        return active

    # ---------- đăng ----------
    def find_own_post(self, caption: str, page_id: str) -> str | None:
        return self.page.evaluate("""data => {
            const norm = v => v.replace(/\\s+/g, ' ').trim();
            const prefix = norm(data.caption).slice(0, 64);
            const heading = [...document.querySelectorAll('h1')].find(h => h.getBoundingClientRect().height)?.innerText.trim() || '';
            for (const article of document.querySelectorAll('[role="article"]')) {
                if (!prefix || !norm(article.innerText).includes(prefix)) continue;
                const anchors = [...article.querySelectorAll('a[href]')];
                const authored = anchors.some(a => { const u = new URL(a.href);
                    return u.searchParams.get('id') === data.pageId || u.pathname === '/' + data.pageId || (heading && norm(a.innerText) === norm(heading)); });
                if (!authored) continue;
                const link = anchors.find(a => { const u = new URL(a.href);
                    return /\\/(posts|videos|reel)\\/[^/?#]+/.test(u.pathname) || (/^\\/(permalink|story)\\.php$/.test(u.pathname) && u.searchParams.has('story_fbid')); });
                if (link) return link.href;
            }
            return null; }""", {"caption": caption, "pageId": page_id})

    def lookup(self, page: dict, page_id: str, caption: str) -> str | None:
        """Tìm bài vừa đăng trên Page (bảng tin rồi tab Thước phim). Chỉ đọc, không đăng."""
        self.goto(page["url"])
        self.page.evaluate("window.scrollTo(0, 1000)")
        time.sleep(4)
        found = self.find_own_post(caption, page_id)
        if found:
            return found
        if not self.click(r"^(Reels|Thước phim)$", '[role="tab"],a[href*="sk=reels"],a[href*="/reels/"]'):
            return None
        time.sleep(5)
        urls = self.page.evaluate("""() => [...new Set([...document.querySelectorAll('a[href]')].map(a => a.href)
            .filter(h => { const u = new URL(h); return /(^|\\.)facebook\\.com$/.test(u.hostname) && /^\\/reel\\/\\d+/.test(u.pathname); }))].slice(0, 5)""")
        prefix = re.sub(r"\s+", " ", caption).strip()[:64]
        for url in urls:
            self.goto(url)
            time.sleep(4)
            if prefix and prefix in re.sub(r"\s+", " ", self.page.inner_text("body")):
                return url
        return None

    def publish(self, file: str, caption: str, page: dict, page_id: str, before_click, log=lambda m: None) -> str:
        """Tải video lên composer của Page và bấm Đăng. before_click() phải ghi nhật ký 'đã gửi' trước khi bấm."""
        p = self.page
        p.wait_for_function("""() => [...document.querySelectorAll('[role="button"],button,a')].some(el =>
            el.getBoundingClientRect().height && /^(Photo\\/video|Ảnh\\/video)$/i.test((el.getAttribute('aria-label') || el.innerText || '').trim()))""",
                            timeout=30_000)
        old_links = set(p.evaluate("() => [...document.querySelectorAll('a[href]')].map(a => a.href)"))
        if self.click(r"^(What's on your mind\??|Bạn đang nghĩ gì\??)(,.*)?$"):
            p.wait_for_selector('[role="dialog"] [contenteditable="true"]', timeout=20_000)
            self.click(r"^(Photo/video|Ảnh/video)$", '[role="dialog"] [role="button"],[role="dialog"] button')
        elif not self.click(r"^(Photo/video|Ảnh/video)$"):
            raise RuntimeError("Không thấy nút Ảnh/video của Page.")
        p.wait_for_selector('input[type="file"]', state="attached", timeout=15_000)
        chosen = None
        for candidate in p.query_selector_all('input[type="file"]'):
            info = candidate.evaluate("el => ({video: /video/i.test(el.accept), dialog: !!el.closest('[role=\"dialog\"]'), any: !el.accept})")
            if info["video"]:
                chosen = candidate
                break
            if info["dialog"] or info["any"]:
                chosen = candidate
        if not chosen:
            raise RuntimeError("Không tìm thấy ô tải video.")

        uploads = {"open": set(), "last": time.time()}
        upload_host = re.compile(r"^(rupload|vupload)[\w.-]*\.facebook\.com$")

        def is_upload(r):
            if r.method == "GET":
                return False
            u = urlparse(r.url)
            return bool(upload_host.match(u.hostname or "")) or "/video-upload/" in u.path or "/upload/video" in u.path

        def started(r):
            if is_upload(r):
                uploads["open"].add(r)
                uploads["last"] = time.time()

        def ended(r):
            if r in uploads["open"]:
                uploads["open"].discard(r)
                uploads["last"] = time.time()

        p.on("request", started)
        p.on("requestfinished", ended)
        p.on("requestfailed", ended)
        busy = lambda quiet: bool(uploads["open"]) or time.time() - uploads["last"] < quiet

        log("Đang tải video lên Facebook…")
        chosen.set_input_files(file)
        p.wait_for_function("""() => !!document.querySelector('[role="dialog"] [contenteditable="true"]') ||
            [...document.querySelectorAll('[role="dialog"]')].some(el => /Something went wrong|Đã xảy ra lỗi/i.test(el.innerText))""",
                            timeout=60_000)
        if p.evaluate("""() => [...document.querySelectorAll('[role="dialog"]')].some(el => /Something went wrong|Đã xảy ra lỗi/i.test(el.innerText))"""):
            raise RuntimeError("Facebook báo lỗi khi mở video. Chưa bấm Đăng.")
        deadline = time.time() + 30 * 60
        publish_re = r"^(Post|Publish|Publish reel|Share|Share now|Đăng|Đăng ngay|Chia sẻ|Chia sẻ ngay)$"
        in_dialog = '[role="dialog"] [role="button"],[role="dialog"] button'
        uploading = """() => [...document.querySelectorAll('[role="dialog"]')].some(el => /Uploading|Đang tải lên/i.test(el.innerText))"""
        committed = False
        while time.time() < deadline:
            self.check()
            publish = self.buttons(publish_re, in_dialog)
            if len(publish) == 1:
                # Nút Đăng bật sớm khi video còn đang tải; chỉ bấm khi đã gửi xong file.
                if busy(15) or p.evaluate(uploading):
                    time.sleep(2.5)
                    continue
                field = None
                for f in p.query_selector_all('[role="dialog"] [contenteditable="true"], [role="dialog"] textarea'):
                    usable = f.evaluate("""el => { const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false;
                        const hit = document.elementFromPoint(Math.max(0, Math.min(innerWidth - 1, r.x + r.width / 2)), Math.max(0, Math.min(innerHeight - 1, r.y + r.height / 2)));
                        return hit && (el === hit || el.contains(hit)); }""")
                    if usable:
                        field = f
                if not field:
                    raise RuntimeError("Không thấy ô mô tả ở bước đăng cuối; chưa bấm Đăng.")
                if field.evaluate("el => el.value ?? el.innerText") != caption:
                    field.click()
                    field.evaluate("""el => { el.focus(); if (el instanceof HTMLTextAreaElement) el.select(); else {
                        const r = document.createRange(); r.selectNodeContents(el); const s = getSelection(); s.removeAllRanges(); s.addRange(r); } }""")
                    p.keyboard.type(caption)
                before_click()
                committed = True
                log("Đã bấm Đăng, đang chờ Facebook xác nhận…")
                publish[0].click()
                break
            if self.click(r"^(Next|Tiếp|Tiếp theo)$", in_dialog):
                time.sleep(1.5)
            else:
                time.sleep(2.5)
        if not committed:
            raise RuntimeError("Tải/xử lý video quá thời gian. Chưa bấm Đăng.")

        view = re.compile(r"^(View post|View video|View reel|View your reel|See post|See reel|See your reel|Xem bài viết|Xem video|Xem reel|Xem thước phim)$", re.I)
        start = time.time()
        refreshed = False
        try:
            while time.time() - start < 5 * 60:
                time.sleep(2)
                self.check()
                links = p.evaluate("() => [...document.querySelectorAll('a[href]')].map(a => ({url: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim()}))")
                fresh = [a for a in links if a["url"] not in old_links and (urlparse(a["url"]).hostname or "").endswith("facebook.com") and POST_LINK.search(urlparse(a["url"]).path)]
                link = next((a for a in fresh if view.match(a["text"])), None) or next((a for a in fresh if page_id in a["url"]), None)
                if link:
                    return link["url"]
                own = self.find_own_post(caption, page_id)
                if own:
                    return own
                if not refreshed and time.time() - start > 15:
                    submitting = busy(15) or p.evaluate("""() => [...document.querySelectorAll('[role="dialog"]')].some(el => el.getBoundingClientRect().height &&
                        /Reel settings|Edit reel|Uploading|Posting|Publishing|Cài đặt thước phim|Chỉnh sửa thước phim|Đang tải lên|Đang đăng/i.test(el.innerText))""")
                    if not submitting:
                        refreshed = True
                        self.goto(page["url"])
                        p.evaluate("window.scrollTo(0, 1000)")
                        time.sleep(4)
            if busy(0):
                raise Uncertain("Đã bấm Đăng nhưng video vẫn đang tải lên. Kiểm tra Page trước khi thử lại.")
            found = self.lookup(page, page_id, caption)
            if found:
                return found
        except AuthRequired:
            raise Uncertain("Đã bấm Đăng nhưng Facebook yêu cầu đăng nhập lại trước khi xác nhận. Kiểm tra Page.")
        raise Uncertain("Đã bấm Đăng nhưng chưa lấy được link bài. Kiểm tra Page trước khi thử lại.")
