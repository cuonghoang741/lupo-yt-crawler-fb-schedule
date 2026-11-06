"""Hồi quy mở trình duyệt, định tuyến tài khoản và thông báo lỗi đăng nhập."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app
import fbpost
import browser_support as support
import webserver


class BrowserDiscovery(unittest.TestCase):
    def test_windows_user_install_with_spaces_and_nonstandard_registry_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chrome = root / "User Data" / "Google" / "Chrome" / "Application" / "chrome.exe"
            chrome.parent.mkdir(parents=True)
            chrome.write_bytes(b"fixture")
            env = {"LOCALAPPDATA": str(root / "User Data")}
            with patch.dict(os.environ, env, clear=True), patch.object(support, "_registry_paths", return_value=[]), patch.object(support.shutil, "which", return_value=None):
                self.assertEqual(support.chromium_path("chrome", "Windows"), str(chrome.resolve()))
            custom = root / "Custom Browser" / "msedge.exe"
            custom.parent.mkdir(); custom.write_bytes(b"fixture")
            with patch.dict(os.environ, {}, clear=True), patch.object(support, "_registry_paths", return_value=[custom]), patch.object(support.shutil, "which", return_value=None):
                self.assertEqual(support.chromium_path("msedge", "Windows"), str(custom.resolve()))

    def test_registry_reads_user_and_machine_app_paths(self):
        handle = MagicMock()
        registry = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_READ=4,
                                   KEY_WOW64_64KEY=8, KEY_WOW64_32KEY=16,
                                   OpenKey=MagicMock(return_value=handle), QueryValueEx=MagicMock(return_value=('"D:\\Apps\\Chrome\\chrome.exe"', 1)))
        with patch.dict("sys.modules", {"winreg": registry}):
            paths = support._registry_paths("chrome")
        self.assertEqual(len(paths), 6)
        self.assertTrue(all(str(p) == r"D:\Apps\Chrome\chrome.exe" for p in paths))
        self.assertEqual({c.args[0] for c in registry.OpenKey.call_args_list}, {1, 2})

    def test_errors_are_specific_and_do_not_treat_every_already_as_locked(self):
        self.assertEqual(support.launch_error(RuntimeError("ProcessSingleton lock"), "chrome").code, "PROFILE_IN_USE")
        self.assertEqual(support.launch_error(RuntimeError("Already subscribed"), "chrome").code, "BROWSER_LAUNCH_FAILED")
        self.assertEqual(support.launch_error(RuntimeError("Executable doesn't exist; playwright install"), "firefox").code, "BROWSER_NOT_INSTALLED")
        self.assertEqual(support.launch_error(PermissionError("private path"), "chrome").code, "PROFILE_NOT_WRITABLE")


class SessionLaunch(unittest.TestCase):
    def fake_driver(self):
        page = MagicMock()
        context = MagicMock(pages=[page])
        pw = MagicMock()
        pw.chromium.launch_persistent_context.return_value = context
        pw.firefox.launch_persistent_context.return_value = context
        return pw, context

    def test_uses_resolved_executable_and_preserves_existing_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            pw, context = self.fake_driver()
            profile = Path(tmp)
            cookie = profile / "existing-profile-marker"
            cookie.write_text("keep")
            with patch("playwright.sync_api.sync_playwright", return_value=SimpleNamespace(start=lambda: pw)), \
                 patch.object(fbpost, "profile_dir", return_value=profile), \
                 patch.object(fbpost, "chromium_path", return_value="D:/Custom Chrome/chrome.exe"):
                with fbpost.Session(True, "chrome", "acct"):
                    pass
            args = pw.chromium.launch_persistent_context.call_args
            self.assertEqual(args.kwargs["executable_path"], "D:/Custom Chrome/chrome.exe")
            self.assertNotIn("channel", args.kwargs)
            self.assertFalse(args.kwargs["headless"])
            self.assertEqual(cookie.read_text(), "keep")
            pw.stop.assert_called_once()

    def test_bundled_chromium_needs_no_installed_chrome_and_keeps_separate_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            pw, context = self.fake_driver()
            with patch("playwright.sync_api.sync_playwright", return_value=SimpleNamespace(start=lambda: pw)), \
                 patch.object(fbpost.ytcore, "app_dir", return_value=Path(tmp)), \
                 patch.object(fbpost, "chromium_path", side_effect=AssertionError("must not search installed Chrome")):
                with fbpost.Session(True, "chromium", "acct"):
                    pass
            args = pw.chromium.launch_persistent_context.call_args
            self.assertEqual(Path(args.args[0]), Path(tmp) / "fb-profile" / "accounts" / "acct" / "chromium")
            self.assertNotIn("executable_path", args.kwargs)

    def test_missing_browser_bundle_reports_setup_and_stops_driver(self):
        with tempfile.TemporaryDirectory() as tmp:
            pw, context = self.fake_driver()
            pw.chromium.launch_persistent_context.side_effect = RuntimeError("Executable doesn't exist; run playwright install")
            with patch("playwright.sync_api.sync_playwright", return_value=SimpleNamespace(start=lambda: pw)), \
                 patch.object(fbpost, "profile_dir", return_value=Path(tmp)):
                with self.assertRaises(support.BrowserLaunchError) as error:
                    fbpost.Session(True, "chromium", "acct")
            self.assertEqual(error.exception.code, "BROWSER_NOT_INSTALLED")
            self.assertIn("setup.bat", str(error.exception))
            pw.stop.assert_called_once()

    def test_navigation_timeout_keeps_login_window_open_for_manual_use(self):
        page = MagicMock()
        page.goto.side_effect = RuntimeError("Navigation timeout of 30000 ms exceeded")
        context = SimpleNamespace(pages=[page], on=lambda *args: None)
        page.wait_for_timeout.side_effect = lambda ms: context.pages.clear()
        session = MagicMock(page=page, context=context)
        session.__enter__.return_value = session
        opened = []
        with patch.object(fbpost, "Session", return_value=session):
            fbpost.login_until_closed(on_open=lambda: opened.append(True))
        self.assertEqual(opened, [True])
        page.wait_for_timeout.assert_called_once()


class ConnectionApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.api = app.Api(app.Store(self.root / "accounts.json"), start_worker=False)
        self.aid = self.api.store.account()["id"]

    def tearDown(self):
        self.api.shutdown()
        self.tmp.cleanup()

    def test_missing_chrome_is_visible_on_account_immediately(self):
        self.api.store.update_account(self.aid, browser="chrome")
        with patch.object(fbpost, "chromium_path", return_value=None):
            with self.assertRaises(support.BrowserLaunchError):
                self.api.do_login({"account_id": self.aid})
        state = self.api.snapshot()["connection"]
        self.assertEqual(state["state"], "error")
        self.assertEqual(state["code"], "BROWSER_NOT_FOUND")
        self.assertIn("Chromium", state["message"])
        self.assertTrue(list((self.root / "logs").glob("*.log")))

    def test_double_click_queues_once_and_keeps_original_account(self):
        self.api.store.update_account(self.aid, browser="chromium")
        self.api.do_login({"account_id": self.aid})
        self.api.do_login({"account_id": self.aid})
        self.assertEqual(self.api.commands.qsize(), 1)
        b = self.api.do_add_account({"label": "Khác", "browser": "chromium"})["account_id"]
        self.api.do_select_account({"account_id": b})
        self.assertEqual(self.api.commands.get_nowait(), ("login", self.aid))
        self.assertFalse(self.api.snapshot()["connection_busy"])
        self.assertEqual(self.api.store.account(self.aid)["connection"]["state"], "queued")

    def test_worker_failure_is_persisted_and_no_longer_busy(self):
        self.api.store.update_account(self.aid, browser="chromium")
        with patch.object(fbpost, "login_until_closed", side_effect=support.BrowserLaunchError("Chạy setup.bat", "BROWSER_NOT_INSTALLED")):
            worker = threading.Thread(target=self.api._run)
            worker.start()
            self.api.do_login({"account_id": self.aid})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and (self.api.store.account(self.aid).get("connection") or {}).get("state") != "error":
                time.sleep(.01)
            self.api.stop.set(); worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.api.snapshot()["connection"]["code"], "BROWSER_NOT_INSTALLED")
        self.assertFalse(self.api.snapshot()["connection_busy"])
        self.assertEqual(json.loads(self.api.store.path.read_text())["accounts"][0]["connection"]["state"], "error")

    def test_opened_callback_marks_actual_window_and_check_runs_after_close(self):
        events = []
        def login(**kwargs):
            self.assertEqual(self.api.store.account(self.aid)["connection"]["state"], "opening")
            kwargs["on_open"]()
            events.append(self.api.store.account(self.aid)["connection"]["state"])
        with patch.object(fbpost, "login_until_closed", side_effect=login), patch.object(self.api, "_check", side_effect=lambda aid: events.append("checked")):
            self.api._handle("login", self.aid)
        self.assertEqual(events, ["login", "checked"])

    def test_cannot_change_browser_or_delete_account_during_login(self):
        self.api.store.update_account(self.aid, browser="chromium")
        self.api.do_login({"account_id": self.aid})
        with self.assertRaises(ValueError):
            self.api.do_set_browser({"account_id": self.aid, "browser": "firefox"})
        with self.assertRaises(ValueError):
            self.api.do_remove_account({"account_id": self.aid})


if __name__ == "__main__":
    unittest.main()
