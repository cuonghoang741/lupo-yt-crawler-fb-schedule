"""Phiên YouTube lưu trên máy; chỉ xuất cookie YouTube, không dùng hồ sơ Facebook."""
from __future__ import annotations

import io
import json
import os
import threading
import time
from http.cookiejar import Cookie, MozillaCookieJar
from pathlib import Path

import ytcore

MODES = {"none": "Không đăng nhập", "saved": "Phiên đã lưu / cookies.txt",
         "chrome": "Cookie Chrome trên máy", "msedge": "Cookie Edge trên máy", "firefox": "Cookie Firefox trên máy"}
AUTH_NAMES = {"LOGIN_INFO", "SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "SID"}


def youtube_domain(domain):
    host = domain.lstrip(".").lower()
    return host == "youtube.com" or host.endswith(".youtube.com")


def cookie_text(cookies: list[dict]) -> str:
    jar = MozillaCookieJar()
    for c in cookies:
        domain = c.get("domain", "")
        expiry = c.get("expires", -1)
        if not youtube_domain(domain) or (expiry > 0 and expiry <= time.time()):
            continue
        jar.set_cookie(Cookie(0, c["name"], c["value"], None, False, domain, domain.startswith("."),
                              domain.startswith("."), c.get("path") or "/", True, bool(c.get("secure")),
                              int(expiry) if expiry > 0 else None, expiry <= 0, None, None,
                              {"HTTPOnly": ""} if c.get("httpOnly") else {}, False))
    if not any(c.name in AUTH_NAMES and c.value for c in jar):
        raise ValueError("Chưa thấy phiên đăng nhập YouTube. Đăng nhập rồi mở youtube.com trước khi lưu cookie.")
    lines = ["# Netscape HTTP Cookie File"]
    for c in jar:
        domain = ("#HttpOnly_" if c.has_nonstandard_attr("HTTPOnly") else "") + c.domain
        fields = [domain, "TRUE" if c.domain_initial_dot else "FALSE", c.path,
                  "TRUE" if c.secure else "FALSE", str(c.expires or 0), c.name, c.value]
        if any("\n" in field or "\r" in field or "\t" in field for field in fields):
            raise ValueError("Cookie không hợp lệ.")
        lines.append("\t".join(fields))
    return "\n".join(lines) + "\n"


def validate_export(text: str) -> str:
    """Đọc Netscape TXT, bỏ mọi domain khác và không đưa dòng chứa secret vào lỗi."""
    if len(text.encode("utf-8")) > 2_000_000:
        raise ValueError("File cookie tối đa 2 MB.")
    text = text.lstrip("\ufeff")
    if not text.startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File")):
        raise ValueError("Chọn file cookies.txt định dạng Netscape, không phải JSON hay Cookie Header.")
    result = []
    for line in text.splitlines():
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        parts = line.removeprefix("#HttpOnly_").split("\t")
        if len(parts) != 7:
            raise ValueError("File cookie sai định dạng. Xuất lại cookies.txt từ trình duyệt.")
        domain, include, path, secure, expires, name, value = parts
        try:
            expiry = int(expires) if expires else 0
        except ValueError:
            raise ValueError("File cookie có thời hạn không hợp lệ.") from None
        result.append({"domain": domain, "path": path, "secure": secure == "TRUE", "expires": expiry,
                       "name": name, "value": value, "httpOnly": line.startswith("#HttpOnly_")})
    return cookie_text(result)


def atomic_private(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        os.chmod(tmp, 0o600)
        f.write(text)
    tmp.replace(path)


class YouTubeAuth:
    def __init__(self, root=None):
        self.root = Path(root) if root else ytcore.app_dir() / "youtube-session"
        self.lock = threading.RLock()
        self.busy = False
        self.message = ""
        self.stop = threading.Event()
        try:
            self.config = json.loads((self.root / "config.json").read_text("utf-8"))
        except (OSError, ValueError):
            self.config = {"mode": "none", "browser": "chrome"}
        if not isinstance(self.config, dict):
            self.config = {"mode": "none", "browser": "chrome"}

    @property
    def cookie_file(self):
        return self.root / "cookies.txt"

    def snapshot(self):
        with self.lock:
            return {"mode": self.config.get("mode", "none"), "browser": self.config.get("browser", "chrome"),
                    "has_cookies": self.cookie_file.is_file(), "busy": self.busy, "message": self.message,
                    "modes": [{"id": k, "label": v} for k, v in MODES.items()]}

    def set_mode(self, mode):
        with self.lock:
            if self.busy:
                raise ValueError("Đóng cửa sổ đăng nhập YouTube trước khi đổi phiên.")
            if mode not in MODES:
                raise ValueError("Nguồn cookie không hợp lệ.")
            if mode == "saved" and not self.cookie_file.is_file():
                raise ValueError("Đăng nhập YouTube hoặc nhập cookies.txt trước.")
            self.config["mode"] = mode
            atomic_private(self.root / "config.json", json.dumps(self.config))

    def save_cookies(self, text):
        with self.lock:
            atomic_private(self.cookie_file, validate_export(text))
            self.config["mode"] = "saved"
            atomic_private(self.root / "config.json", json.dumps(self.config))

    def import_file(self, path):
        with self.lock:
            if self.busy:
                raise ValueError("Đóng cửa sổ YouTube trước khi nhập cookie.")
            p = Path(path)
            if p.stat().st_size > 2_000_000:
                raise ValueError("File cookie tối đa 2 MB.")
            try:
                self.save_cookies(p.read_text("utf-8-sig"))
            except UnicodeError:
                raise ValueError("File cookie phải là file TXT UTF-8 định dạng Netscape.") from None
            self.message = "Đã lưu cookie YouTube trên máy. Bấm Thử lại mục lỗi để tải tiếp."

    def login(self, browser="chrome"):
        import fbpost
        with self.lock:
            if self.busy:
                raise ValueError("Cửa sổ YouTube đang mở. Đăng nhập rồi đóng cửa sổ đó.")
            browser = fbpost.normalize_browser(browser)
            self.busy = True
            self.stop.clear()
            self.config["browser"] = browser
            self.message = "Đăng nhập và xác minh trong trình duyệt, mở YouTube rồi đóng cửa sổ khi xong."
        threading.Thread(target=self._login, args=(browser,), daemon=True).start()

    def _login(self, browser):
        saved = False
        try:
            import fbpost
            from playwright.sync_api import sync_playwright
            spec = fbpost.BROWSERS[browser]
            if spec["engine"] == "chromium" and not fbpost.chromium_path(spec["channel"]):
                raise RuntimeError("Chưa cài trình duyệt đã chọn trên máy.")
            profile = self.root / "profiles" / browser
            profile.mkdir(parents=True, exist_ok=True)
            with sync_playwright() as pw:
                kwargs = {"headless": False, "viewport": {"width": 1280, "height": 900}}
                if spec["channel"]:
                    kwargs["channel"] = spec["channel"]
                context = getattr(pw, spec["engine"]).launch_persistent_context(str(profile), **kwargs)
                last = ""
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=60000)
                    deadline = time.monotonic() + 15 * 60
                    while not self.stop.is_set() and context.pages and time.monotonic() < deadline:
                        try:
                            text = cookie_text(context.cookies())
                            if text != last:
                                self.save_cookies(text)
                                last, saved = text, True
                                self.message = "Đã lưu phiên YouTube. Đóng cửa sổ khi xong rồi bấm Tiếp tục / thử lại lỗi."
                        except ValueError:
                            pass  # đang ở Google hoặc chưa hoàn tất đăng nhập
                        context.pages[0].wait_for_timeout(1000)
                except Exception:
                    if context.pages:
                        raise
                finally:
                    context.close()
            self.message = "Đã lưu phiên YouTube. Bấm Thử lại mục lỗi." if saved else "Chưa lưu được đăng nhập. Có thể nhập cookies.txt từ trình duyệt đã đăng nhập."
        except Exception:
            # Lỗi trình duyệt có thể chứa đường dẫn hồ sơ; không gửi chi tiết/secret lên UI.
            self.message = "Chưa lưu được phiên YouTube. Chạy lại setup.bat hoặc nhập cookies.txt từ trình duyệt đã đăng nhập."
        finally:
            self.busy = False

    def forget(self):
        with self.lock:
            self.set_mode("none")
            self.cookie_file.unlink(missing_ok=True)
            self.message = "Đã bỏ cookie dùng để tải. Hồ sơ đăng nhập vẫn nằm trên máy."

    def options(self):
        mode = self.config.get("mode", "none")
        if mode == "saved":
            try:
                text = validate_export(self.cookie_file.read_text("utf-8"))
            except (OSError, ValueError):
                raise ValueError("Cookie YouTube đã hết hạn hoặc không đọc được. Đăng nhập/nhập cookie lại.") from None
            return {"cookiefile": io.StringIO(text)}  # yt-dlp ghi lại vào bản sao trong RAM
        if mode in ("chrome", "msedge", "firefox"):
            return {"cookiesfrombrowser": ("edge" if mode == "msedge" else mode,)}
        return {}
