"""Kiểm tra UI thật và bridge loopback; không truy cập Facebook thật."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import automation
import fbpost
import webapp

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "cần playwright")
class WebUi(unittest.TestCase):
    def test_multi_account_forms_and_queue_through_real_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(webapp, "load_settings", return_value={"output": str(Path(tmp) / "videos")}):
                store = automation.Store(Path(tmp) / "automation.json")
                api = webapp.Api(store, start_engine=False)
            server = webapp.Server(api)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel="chrome", headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 1280, "height": 900})
                        page.set_default_timeout(45000)
                        errors = []
                        page.on("pageerror", lambda err: errors.append(str(err)))
                        page.goto(server.url)
                        page.locator('#account-select option[value="default"]').wait_for(state="attached")
                        page.locator('[data-k="facebook"]').first.click()
                        page.locator('#new-acc-label').fill('TK B <img src=x onerror=alert(1)>')
                        page.locator('#new-acc-browser').select_option("firefox")
                        page.locator('[data-act="add_account"]').click()
                        page.wait_for_function("() => document.querySelector('#account-select').value !== 'default'")
                        b = page.locator('#account-select').input_value()
                        self.assertEqual(store.account(b)["browser"], "firefox")
                        self.assertEqual(page.locator('#acc-rows img').count(), 0)
                        pa = {"name": "Page A", "url": "https://www.facebook.com/profile.php?id=111"}
                        pb = {"name": "Page B", "url": "https://www.facebook.com/profile.php?id=222"}
                        store.update_account("default", available_pages=[pa], account={"ok": True, "id": "1"})
                        store.update_account(b, available_pages=[pb], account={"ok": True, "id": "2"})
                        page.reload()
                        page.locator('#account-select option').nth(1).wait_for(state="attached")
                        page.locator('[data-k="schedule"]').first.click()
                        page.get_by_label('Page B', exact=False).check()
                        self.assertEqual(page.locator('input[name="sc-page"]').count(), 1)
                        page.locator('#sc-slots').fill("11:30, 20h")
                        page.locator('#sc-cap').fill("B {title}")
                        page.locator('[data-act="save_schedule"]').click()
                        page.wait_for_function("() => document.querySelector('#sc-state')?.textContent.includes('Đã lưu')")
                        self.assertEqual(store.account(b)["pages"], [pb])
                        page.locator('#account-select').select_option("default")
                        page.get_by_label('Page A', exact=False).check()
                        self.assertEqual(page.locator('#sc-cap').input_value(), "{title}\n\n{hashtags}")
                        page.locator('#sc-slots').fill("08:15")
                        page.locator('#sc-cap').fill("A {title}")
                        page.locator('[data-act="save_schedule"]').click()
                        page.wait_for_function("() => document.querySelector('#sc-state')?.textContent.includes('Đã lưu')")
                        page.locator('[data-k="facebook"]').first.click()
                        page.locator('[data-act="scan_pages"]').click()
                        page.locator('#account-select').select_option(b)
                        page.wait_for_function("() => document.querySelector('#fb-browser')?.value === 'firefox'")
                        self.assertEqual(api.engine.commands.get_nowait(), ("scan_pages", "default"))
                        self.assertEqual(store.account(b)["caption"], "B {title}")
                        self.assertEqual(store.account("default")["caption"], "A {title}")
                        self.assertEqual(errors, [])
                    finally:
                        browser.close()
                # Bridge từ chối request thiếu token/Origin, dù biết cổng local.
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(server.origin + "/api/state", data=b"{}", headers={"Content-Type": "application/json"}), timeout=5)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


@unittest.skipIf(sync_playwright is None, "cần playwright")
class PageDiscovery(unittest.TestCase):
    def test_reads_managed_cards_and_excludes_suggested_pages(self):
        html = '''<main role="main"><h1>Pages</h1>
        <article><a href="https://www.facebook.com/profile.php?id=111">Page A</a><button>Manage</button></article>
        <article><a href="https://www.facebook.com/page.b">Page B</a><button>Quản lý</button></article>
        <section><h2>Suggested Pages</h2><article><a href="https://www.facebook.com/suggestion">Gợi ý</a><button>Follow</button></article></section>
        <article><a href="https://evilfacebook.com/abc">Lừa</a><button>Manage</button></article>
        <a href="https://www.facebook.com/settings">Settings</a></main>'''
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context()
                context.add_cookies([{"name": "c_user", "value": "99", "url": "https://www.facebook.com"}])
                page = context.new_page()
                page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html))
                result = fbpost.Session.wrap(context, page).managed_pages()
                self.assertEqual(result, [
                    {"name": "Page A", "url": "https://www.facebook.com/profile.php?id=111"},
                    {"name": "Page B", "url": "https://www.facebook.com/page.b"}])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
