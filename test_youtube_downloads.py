"""Phiên YouTube, hàng đợi phục hồi và xử lý yêu cầu xác minh; không tải YouTube thật."""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

import automation
import webapp
import ytcore
from youtube_auth import YouTubeAuth, cookie_text, validate_export

COOKIE = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tLOGIN_INFO\tprivate-youtube-session\n"
V1 = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
V2 = "https://www.youtube.com/watch?v=bbbbbbbbbbb"


class YoutubeDownloads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        with patch.object(webapp, "load_settings", return_value={"output": str(self.root / "videos")}):
            self.api = webapp.Api(automation.Store(self.root / "automation.json"), start_engine=False)
        self.worker = patch.object(self.api, "_ensure_worker")
        self.worker.start()
        self.api.tools = {"ffmpeg": "ffmpeg", "deno": "deno"}

    def tearDown(self):
        self.api.shutdown()
        self.worker.stop()
        self.tmp.cleanup()

    def test_import_keeps_only_youtube_cookies_and_never_exposes_values(self):
        source = self.root / "export.txt"
        source.write_text(COOKIE + ".facebook.com\tTRUE\t/\tTRUE\t0\txs\tfacebook-secret\n")
        self.api.youtube.import_file(source)
        text = self.api.youtube.cookie_file.read_text()
        self.assertIn("private-youtube-session", text)
        self.assertNotIn("facebook-secret", text)
        self.assertNotIn("private-youtube-session", json.dumps(self.api.snapshot()))
        self.assertEqual(self.api.youtube.snapshot()["mode"], "saved")
        with patch.object(ytcore, "app_dir", return_value=self.root):
            opts = ytcore.base_options(self.api.tools)
        from yt_dlp import YoutubeDL
        with YoutubeDL(opts) as ydl:
            self.assertEqual(next(c.value for c in ydl.cookiejar if c.name == "LOGIN_INFO"), "private-youtube-session")
        self.assertEqual(self.api.youtube.cookie_file.read_text(), text)  # yt-dlp sửa bản sao trong RAM

    def test_invalid_or_expired_import_preserves_previous_session(self):
        self.api.youtube.save_cookies(COOKIE)
        before = self.api.youtube.cookie_file.read_bytes()
        for bad in ("secret-not-a-netscape-file", COOKIE.replace("\t0\t", "\t1\t"), COOKIE + "secret-invalid-line"):
            with self.assertRaises(ValueError) as e:
                self.api.youtube.save_cookies(bad)
            self.assertNotIn("secret", str(e.exception))
            self.assertEqual(self.api.youtube.cookie_file.read_bytes(), before)

    def test_saved_session_snapshot_is_read_only_and_browser_selection_is_explicit(self):
        auth = self.api.youtube
        self.assertEqual(auth.options(), {})
        auth.set_mode("msedge")
        self.assertEqual(auth.options(), {"cookiesfrombrowser": ("edge",)})
        auth.save_cookies(COOKIE)
        self.assertIsInstance(auth.options()["cookiefile"], io.StringIO)
        auth.forget()
        self.assertFalse(auth.cookie_file.exists())
        self.assertEqual(auth.options(), {})

    def test_queue_pauses_after_first_auth_error_and_resumes_without_losing_rest(self):
        self.api.do_start_download({"text": V1 + "\n" + V2})
        calls = []
        def blocked(*args):
            calls.append(args[0])
            raise ytcore.download_error(RuntimeError("Sign in to confirm you’re not a bot"))
        with patch.object(webapp.crawl, "download", side_effect=blocked):
            self.api._download_worker()
        self.assertEqual(calls, [V1])
        self.assertTrue(self.api.dl_paused)
        self.assertEqual([j["status"] for j in self.api.jobs], ["Chờ xác minh", "Chờ"])
        with patch.object(webapp, "load_settings", return_value={"output": str(self.root / "videos")}):
            restored = webapp.Api(automation.Store(self.root / "automation.json"), start_engine=False)
        self.assertTrue(restored.dl_paused)
        self.assertEqual([j["url"] for j in restored.jobs], [V1, V2])
        self.api.do_retry_downloads({})
        with patch.object(webapp.crawl, "download", return_value={"title": "Tên giữ nguyên 🕊️", "channel": "Kênh A", "file": "out.mp4"}) as download:
            self.api._download_worker()
        self.assertEqual(download.call_count, 2)
        self.assertFalse(self.api.dl_paused)
        self.assertEqual([j["status"] for j in self.api.jobs], ["Xong", "Xong"])
        self.assertEqual(self.api.jobs[0]["title"], "Tên giữ nguyên 🕊️")

    def test_partial_channel_retry_does_not_duplicate_already_discovered_video(self):
        channel = "https://www.youtube.com/@example"
        self.api.do_start_download({"text": channel})
        source = self.api.jobs[0]
        video = {"id": "aaaaaaaaaaa", "url": V1, "title": "Tiêu đề gốc", "channel": "Ví dụ"}
        def partial(item, tools, callback, stop):
            callback(video)
            raise RuntimeError("fixture network interrupted")
        with patch.object(webapp.crawl, "list_videos", side_effect=partial):
            self.api._dl_channel(source, self.root, 1080)
        def completed(item, tools, callback, stop):
            callback(video)
            callback({**video, "id": "bbbbbbbbbbb", "url": V2})
            return 2
        with patch.object(webapp.crawl, "list_videos", side_effect=completed):
            self.api._dl_channel(source, self.root, 1080)
        self.assertEqual([j["url"] for j in self.api.jobs], [channel, V1, V2])
        self.assertEqual(source["status"], "Xong")

    def test_rate_limit_pauses_while_other_errors_can_continue(self):
        self.api.do_start_download({"text": V1 + "\n" + V2})
        self.api._job_error(self.api.jobs[0], RuntimeError("video unavailable"))
        self.assertFalse(self.api.dl_paused)
        self.api._job_error(self.api.jobs[1], ytcore.download_error(RuntimeError("HTTP Error 429: Too Many Requests")))
        self.assertTrue(self.api.dl_paused)

    def test_import_template_and_retry_single_failed_job(self):
        csv = self.root / "links.csv"
        csv.write_text("title,url\nA," + V1 + "\nB," + V2 + "\n", encoding="utf-8-sig")
        self.api.dialog = lambda kind: str(csv) if kind == "links" else str(self.root / "template.csv")
        self.assertEqual(self.api.do_import_links({})["added"], 2)
        for job in self.api.jobs:
            job["status"] = "Lỗi"
        self.api.do_retry_downloads({"id": self.api.jobs[0]["id"]})
        self.assertEqual([j["status"] for j in self.api.jobs], ["Chờ", "Lỗi"])
        self.api.do_download_template({})
        self.assertEqual(ytcore.parse_import((self.root / "template.csv").read_text("utf-8-sig"))[0].kind, "channel")

    def test_local_video_import_keeps_title_and_is_visible_in_library(self):
        files = [self.root / "Tiêu đề gốc 🕊️.mp4", self.root / "Video khác.mkv"]
        for f in files:
            f.write_bytes(b"local-video-fixture")
        self.api.dialog = lambda kind: [str(f) for f in files]
        result = self.api.do_import_videos({})
        self.assertEqual(result["added"], 2)
        videos = ytcore.scan_library(Path(self.api.output))
        self.assertEqual({v["title"] for v in videos}, {f.stem for f in files})
        self.assertEqual({Path(v["file"]).suffix for v in videos}, {".mp4", ".mkv"})
        self.assertEqual(ytcore.safe_stem("CON"), "CON_")

    def test_stale_running_job_returns_to_pending_after_restart(self):
        self.api.do_start_download({"text": V1})
        self.api.jobs[0]["status"] = "Đang chạy"
        self.api._save_queue()
        with patch.object(webapp, "load_settings", return_value={"output": str(self.root / "videos")}):
            restored = webapp.Api(automation.Store(self.root / "automation.json"), start_engine=False)
        self.assertEqual(restored.jobs[0]["status"], "Chờ")

    def test_thumbnail_endpoint_only_serves_registered_library_image(self):
        image = self.root / "thumb.jpg"
        image.write_bytes(b"local-jpeg-fixture")
        link = self.api._thumbnail(str(image))
        server = webapp.Server(self.api)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with urlopen(server.origin + link, timeout=5) as response:
                self.assertEqual(response.read(), image.read_bytes())
            with self.assertRaises(HTTPError) as error:
                urlopen(server.origin + "/thumbnails/automation.json", timeout=5)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()

    @unittest.skipIf(sync_playwright is None, "cần Playwright")
    def test_youtube_ui_import_cookie_tree_and_retry_through_loopback(self):
        csv = self.root / "links.csv"
        csv.write_text("url\n" + V1 + "\n" + V2 + "\n", encoding="utf-8-sig")
        cookie = self.root / "export.txt"
        cookie.write_text(COOKIE)
        template = self.root / "template.csv"
        self.api.dialog = lambda kind: str({"links": csv, "cookie": cookie, "template": template}[kind])
        server = webapp.Server(self.api)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                try:
                    page = browser.new_page(viewport={"width": 1280, "height": 1000})
                    page.set_default_timeout(45000)
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(server.url)
                    page.locator('#account-select option').wait_for(state="attached")
                    page.locator('[data-k="download"]').first.click()
                    page.locator('[data-act="import_links"]').click()
                    page.wait_for_function("() => document.querySelector('#dl-rows').innerText.includes('aaaaaaaaaaa')")
                    for j in self.api.jobs:
                        j.update(channel="Kênh A", status="Lỗi", progress="Lỗi thử nghiệm")
                    self.api.dl_paused = True
                    self.api.dl_error = "YouTube yêu cầu đăng nhập/xác minh."
                    page.wait_for_function("() => document.querySelector('#dl-notice').innerText.includes('YouTube')")
                    page.locator('#yt-auth summary').click()
                    page.locator('[data-act="youtube_import_cookie"]').click()
                    page.wait_for_function("() => document.querySelector('#yt-mode').value === 'saved'")
                    self.assertNotIn("private-youtube-session", page.locator('body').inner_text())
                    toggle = page.locator('[data-act="toggle_channel"][data-channel="dl:Kênh A"]')
                    toggle.click()
                    self.assertEqual(page.locator('#dl-rows tr').count(), 1)
                    toggle.click()
                    page.locator('#dl-retry').click()
                    page.wait_for_function("() => !document.querySelector('#dl-notice').innerText.includes('YouTube')")
                    self.assertEqual([j["status"] for j in self.api.jobs], ["Chờ", "Chờ"])
                    page.locator('[data-act="download_template"]').click()
                    page.wait_for_timeout(400)
                    self.assertTrue(template.is_file())
                    self.assertEqual(errors, [])
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / "social-hub-v10-youtube.png"))
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
