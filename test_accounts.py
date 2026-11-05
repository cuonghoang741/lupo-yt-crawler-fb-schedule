"""Hồi quy v9: di chuyển v8, định tuyến hồ sơ/lịch và không đăng lại bài chưa rõ."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import accounts
import automation
import fbpost
import webapp


class Accounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(automation, "LOG_DIR", self.root / "logs"),
                        patch.object(webapp, "load_settings", return_value={"output": str(self.root / "videos")})]
        for p in self.patches:
            p.start()
        self.store = automation.Store(self.root / "automation.json")
        self.api = webapp.Api(self.store, start_engine=False)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def connect(self, account_id, page_id):
        page = {"name": "Page " + page_id, "url": "https://www.facebook.com/profile.php?id=" + page_id}
        self.store.update_account(account_id, account={"ok": True, "id": "user-" + account_id},
                                  available_pages=[page], pages=[page])
        return page

    def add(self, label="Tài khoản hai", browser="firefox"):
        return self.api.do_add_account({"label": label, "browser": browser})["account_id"]

    def test_v8_migrates_once_with_backup_and_keeps_history(self):
        old = {"browser": "msedge", "account": {"ok": True, "id": "10", "name": "Cũ"},
               "pages": [{"name": "P", "url": "https://www.facebook.com/123"}],
               "slots": ["19:00"], "enabled": True, "keywords": ["tin"], "reading": True,
               "fired": {"19:00": "2026-11-05"}, "posts": {"v|p": {"state": "uncertain"}},
               "downloads": [{"title": "video cũ"}]}
        path = self.root / "v8.json"
        path.write_text(json.dumps(old))
        store = automation.Store(path)
        account = store.account()
        self.assertEqual(account["id"], "default")
        self.assertEqual(account["slots"], ["19:00"])
        self.assertEqual(account["browser"], "msedge")
        self.assertEqual(account["fired"], old["fired"])
        self.assertEqual(store.data["posts"]["v|p"]["account_id"], "default")
        self.assertEqual(store.data["downloads"], old["downloads"])
        self.assertEqual(json.loads((self.root / "v8.v8-backup.json").read_text()), old)
        store.save()
        self.assertEqual(automation.Store(path).data, store.data)

    def test_schedule_rejects_page_from_other_account_and_saves_separately(self):
        a = "default"
        b = self.add()
        pa, pb = self.connect(a, "111"), self.connect(b, "222")
        self.api.do_save_schedule({"account_id": a, "slots": "10:30", "caption": "A {title}", "page_urls": [pa["url"]]})
        with self.assertRaisesRegex(ValueError, "không thuộc"):
            self.api.do_save_schedule({"account_id": b, "slots": "11:30", "caption": "B", "page_urls": [pa["url"]]})
        self.api.do_save_schedule({"account_id": b, "slots": "11:30", "caption": "B", "page_urls": [pb["url"]]})
        self.assertEqual(self.store.account(a)["slots"], ["10:30"])
        self.assertEqual(self.store.account(b)["slots"], ["11:30"])
        self.api.do_save_advanced({"account_id": a, "keywords": "âm nhạc", "reading": True})
        self.api.do_save_advanced({"account_id": b, "keywords": "công nghệ", "reading": False})
        self.assertTrue(self.store.account(a)["reading"])
        self.assertFalse(self.store.account(b)["reading"])
        self.assertEqual(self.store.account(b)["keywords"], ["công nghệ"])

    def test_queued_command_keeps_account_when_selection_changes(self):
        b = self.add()
        self.api.do_login({"account_id": "default"})
        self.api.do_select_account({"account_id": b})
        self.assertEqual(self.api.engine.commands.get_nowait(), ("login", "default"))
        self.api.do_check_account({"account_id": b})
        self.assertEqual(self.api.engine.commands.get_nowait(), ("check_account", b))

    def test_profiles_are_separate_per_account_and_engine_with_legacy_path(self):
        with patch.object(fbpost.ytcore, "app_dir", return_value=self.root):
            old = self.root / "fb-profile" / "chrome"
            old.mkdir(parents=True)
            (old / "Preferences").write_text("legacy")
            self.assertEqual(fbpost.profile_dir("chrome", "default"), old)
            paths = [fbpost.profile_dir(b, a) for a in ("aa", "bb") for b in fbpost.BROWSERS]
            self.assertEqual(len(set(paths)), 6)
            self.assertTrue(all(p != old for p in paths))
            self.assertEqual((old / "Preferences").read_text(), "legacy")
            with self.assertRaises(ValueError):
                fbpost.profile_dir("chrome", "../../escape")

    def test_wrong_user_identity_is_rejected_before_page_access(self):
        class Context:
            def cookies(self, url):
                return [{"name": "c_user", "value": "unexpected"}]
        s = fbpost.Session.wrap(Context(), None)
        with self.assertRaises(fbpost.AuthRequired):
            s.assert_identity("expected")

    def test_browser_change_requires_recheck_and_cannot_happen_during_work(self):
        self.connect("default", "111")
        self.api.do_set_browser({"account_id": "default", "browser": "firefox"})
        self.assertFalse(self.store.account()["account"]["ok"])
        self.api.engine.busy = True
        with self.assertRaises(ValueError):
            self.api.do_set_browser({"account_id": "default", "browser": "chrome"})

    def test_scan_failure_keeps_previous_pages_but_exposes_error(self):
        self.connect("default", "111")
        before = self.store.account()["pages"][:]
        with patch.object(self.api.engine, "session", side_effect=RuntimeError("fixture offline")):
            self.api.engine.scan_pages("default")
        self.assertEqual(self.store.account()["pages"], before)
        self.assertIn("fixture offline", self.api.snapshot()["pages_error"])

    def test_two_schedules_use_own_profiles_and_do_not_resubmit(self):
        b = self.add()
        self.connect("default", "111")
        self.connect(b, "222")
        video = {"id": "video-one", "modified": 1, "file": "fixture.mp4", "title": "Một video", "url": ""}
        events = []

        class Session:
            def __init__(self, visible, browser, account_id):
                self.account_id = account_id
                events.append(("open", account_id, browser))
            def assert_identity(self, identity):
                assert identity == "user-" + self.account_id
            def switch_page(self, page):
                events.append(("switch", self.account_id, page["name"]))
                return accounts.page_key(page)
            def publish(self, file, caption, page, page_id, before_click, log):
                before_click()
                events.append(("publish", self.account_id, caption))
                return f"https://www.facebook.com/{page_id}/posts/1"
            def close(self):
                pass

        now = automation.datetime.now()
        slot = now.strftime("%H:%M")
        for aid in ("default", b):
            self.store.update_account(aid, enabled=True, slots=[slot], caption=aid + " {title}")
        with patch.object(automation.crawl, "library", return_value=[video]), \
             patch.object(automation.upload, "Session", Session):
            self.api.engine.handle("tick")
            self.api.engine.handle("tick")
        published = [e for e in events if e[0] == "publish"]
        self.assertEqual([e[1] for e in published], ["default", b])
        self.assertEqual([e[2] for e in published], ["default Một video", b + " Một video"])
        self.assertEqual([e[2] for e in events if e[0] == "open"], ["chrome", "firefox"])
        self.assertTrue(all(p["state"] == "posted" for p in self.store.data["posts"].values()))

    def test_uncertain_post_is_not_retried_from_another_account(self):
        b = self.add()
        self.connect(b, "111")
        self.store.set_post("v|https://www.facebook.com/profile.php?id=111", state="uncertain", account_id="default")
        with patch.object(automation.crawl, "library", return_value=[{"id": "v", "modified": 1}]), \
             patch.object(automation.upload, "Session") as session:
            self.api.engine.post_slot(b, manual=True)
        session.assert_not_called()

    def test_crash_markers_survive_migration(self):
        self.store.set_post("a", state="posting")
        self.store.set_post("b", state="preparing")
        automation.Engine(self.store, lambda: None, lambda *args: None)
        self.assertEqual(self.store.data["posts"]["a"]["state"], "uncertain")
        self.assertEqual(self.store.data["posts"]["b"]["state"], "failed")

    def test_rescanning_page_as_numeric_id_does_not_repost_old_vanity_url(self):
        video = {"id": "v", "modified": 1}
        pages = [{"name": "P", "url": "https://www.facebook.com/profile.php?id=111"}]
        posts = {"v|https://www.facebook.com/page.name": {"state": "posted", "page_id": "111"}}
        self.assertIsNone(automation.pick_video([video], pages, posts))
        posts[next(iter(posts))]["state"] = "uncertain"
        self.assertIsNone(automation.pick_video([video], pages, posts))


if __name__ == "__main__":
    unittest.main()
