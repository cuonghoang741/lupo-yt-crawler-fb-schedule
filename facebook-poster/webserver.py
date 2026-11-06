"""HTTP loopback + cửa sổ pywebview dùng chung (token + CSP như Frame Preview).

Mỗi tool tạo một đối tượng `api` có `.snapshot()`, `.action(req)` và tuỳ chọn `.dialog`,
`.shutdown()`; webserver lo phần cửa sổ và cầu nối bảo mật.
"""
from __future__ import annotations

import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, api, html_file):
        super().__init__(("127.0.0.1", 0), Handler)
        self.api = api
        self.html_file = Path(html_file)
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
        if not isinstance(payload, bytes):
            payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
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
            html = self.server.html_file.read_text("utf-8").replace("__NONCE__", self.server.nonce)
            return self.send(200, html.encode("utf-8"), "text/html; charset=utf-8")
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


def run(api, title, html="ui.html", width=1120, height=780):
    try:
        import webview
    except ImportError:
        print("Thiếu pywebview. Chạy setup.bat để cài.")
        return
    server = Server(api, HTML_DIR / html)
    for key in ("ALLOW_DOWNLOADS", "ALLOW_FILE_URLS", "OPEN_EXTERNAL_LINKS_IN_BROWSER"):
        webview.settings[key] = False
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    window = webview.create_window(title, server.url, width=width, height=height,
                                   min_size=(880, 560), background_color="#0F1115")

    vids = ("Video (*.mp4;*.mkv;*.mov;*.webm;*.avi;*.m4v)",)

    def dialog(kind):
        if kind == "files":
            return window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=vids) or []
        if kind == "file":
            picked = window.create_file_dialog(webview.FileDialog.OPEN, file_types=vids)
            return picked[0] if picked else ""
        value = window.create_file_dialog(webview.FileDialog.FOLDER)
        return value[0] if value else ""

    api.dialog = dialog
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        webview.start()
    finally:
        if hasattr(api, "shutdown"):
            api.shutdown()
