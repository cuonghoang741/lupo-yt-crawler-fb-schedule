"""UI thật và cửa sổ thật với Facebook giả lập; không đăng nhập/đăng bài thật."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import app
import fbpost
import browser_support
import webserver


class PosterUi(unittest.TestCase):
    def test_login_error_visible_and_page_checkbox_survives_polling(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = app.Api(app.Store(Path(tmp) / "accounts.json"), start_worker=False)
            aid = api.store.account()["id"]
            api.store.update_account(aid, browser="chrome", available_pages=[{"name": "Page thử", "url": "https://www.facebook.com/123"}])
            server = webserver.Server(api, Path(__file__).with_name("ui.html"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.object(fbpost, "chromium_path", return_value=None), \
                     patch.object(app, "preferred_browser", return_value="chromium"), sync_playwright() as pw:
                    browser = pw.chromium.launch(channel="chrome", headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 1280, "height": 1000})
                        page.set_default_timeout(30000)
                        errors = []
                        page.on("pageerror", lambda e: errors.append(str(e)))
                        page.goto(server.url)
                        page.locator('#ac-browser option').nth(3).wait_for(state="attached")
                        self.assertEqual(page.locator('#ac-browser').input_value(), "chromium")
                        page.locator('#login-btn').click()
                        page.get_by_text("BROWSER_NOT_FOUND", exact=False).first.wait_for()
                        self.assertIn("Chromium", page.locator('#connection-status').inner_text())
                        self.assertFalse(page.locator('#login-btn').is_disabled())
                        page.locator('#sel-browser').select_option("chromium")
                        page.wait_for_function("() => document.querySelector('#connection-status').textContent === ''")
                        page.locator('#login-btn').click()
                        page.wait_for_function("() => document.querySelector('#login-btn').disabled")
                        self.assertEqual(api.commands.qsize(), 1)
                        self.assertEqual(api.commands.queue[0], ("login", aid))
                        page.locator('[data-k="post"]').click()
                        page.locator('.pg-pick').check()
                        page.wait_for_timeout(2000)
                        self.assertTrue(page.locator('.pg-pick').is_checked())
                        self.assertEqual(errors, [])
                        page.locator('[data-k="accounts"]').click()
                        page.screenshot(path=str(Path(tempfile.gettempdir()) / "facebook-poster-login-fix.png"))
                    finally:
                        browser.close()
            finally:
                api.shutdown()
                server.shutdown(); server.server_close()

    def test_visible_browsers_open_close_and_reuse_private_profile(self):
        original_session = fbpost.Session
        original_login = fbpost.login_until_closed
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api = app.Api(app.Store(root / "accounts.json"), start_worker=False)
            aid = api.store.account()["id"]
            opened = []
            def fixture_session(*args, **kwargs):
                s = original_session(*args, **kwargs)
                s.context.route("**/*", lambda r: r.fulfill(status=200, content_type="text/html", body='<title>Fixture User | Facebook</title><main role="main">Local login fixture</main>'))
                s.context.add_cookies([{"name": "c_user", "value": "123", "url": "https://www.facebook.com", "expires": int(time.time()) + 3600}])
                return s
            def short_login(**kwargs):
                before = kwargs["on_open"]
                def on_open():
                    before()
                    opened.append(api.store.account(aid)["browser"])
                kwargs["on_open"] = on_open
                return original_login(timeout_s=.2, **kwargs)
            with patch.object(fbpost.ytcore, "app_dir", return_value=root), \
                 patch.object(fbpost, "Session", side_effect=fixture_session), \
                 patch.object(fbpost, "login_until_closed", side_effect=short_login):
                for kind in ("chrome", "chromium"):
                    api.store.update_account(aid, browser=kind)
                    api._handle("login", aid)
                    self.assertEqual(api.store.account(aid)["connection"]["state"], "ready")
                    self.assertTrue(api.store.account(aid)["account"]["ok"])
                    self.assertTrue((root / "fb-profile" / kind).is_dir())
            self.assertEqual(opened, ["chrome", "chromium"])


if __name__ == "__main__":
    unittest.main()
