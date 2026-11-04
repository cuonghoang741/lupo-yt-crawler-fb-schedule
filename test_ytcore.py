import tempfile
import unittest
from pathlib import Path

from ytcore import delete_video, parse_import, scan_library, youtube_input


class Links(unittest.TestCase):
    def test_video_forms(self):
        for link in [
            "https://www.youtube.com/watch?v=KljvrvLL1ug&t=3",
            "https://youtu.be/KljvrvLL1ug",
            "https://www.youtube.com/shorts/KljvrvLL1ug",
        ]:
            self.assertEqual(youtube_input(link).url, "https://www.youtube.com/watch?v=KljvrvLL1ug")

    def test_channel_tabs_collapse_to_root(self):
        self.assertEqual(youtube_input("https://www.youtube.com/@ChosenByHeavens/videos").url,
                         "https://www.youtube.com/@ChosenByHeavens")
        self.assertEqual(youtube_input("https://www.youtube.com/@ChosenByHeavens").kind, "channel")

    def test_rejects_other_sites_and_http(self):
        for link in ["https://vimeo.com/1", "http://youtube.com/watch?v=KljvrvLL1ug", "https://www.youtube.com/feed"]:
            with self.assertRaises(ValueError):
                youtube_input(link)

    def test_csv_with_header_and_duplicates(self):
        text = "﻿title;url\nA;https://youtu.be/KljvrvLL1ug\nB;https://www.youtube.com/watch?v=KljvrvLL1ug\n"
        self.assertEqual(len(parse_import(text)), 1)

    def test_plain_lines_and_error_row(self):
        self.assertEqual(len(parse_import("https://youtu.be/KljvrvLL1ug\nhttps://www.youtube.com/@x\n")), 2)
        with self.assertRaisesRegex(ValueError, "Dòng 2"):
            parse_import("https://youtu.be/KljvrvLL1ug\nabc\n")


class Library(unittest.TestCase):
    def test_scan_and_delete(self):
        out = Path(tempfile.mkdtemp())
        ch = out / "Kênh A"
        ch.mkdir()
        (ch / "Clip [KljvrvLL1ug].mp4").write_bytes(b"x" * 10)
        (ch / "Clip [KljvrvLL1ug].jpg").write_bytes(b"j")
        (ch / "Clip [KljvrvLL1ug].info.json").write_text('{"id":"KljvrvLL1ug","title":"Clip","channel":"Kênh A"}', encoding="utf-8")
        (out / ".da-tai.txt").write_text("youtube KljvrvLL1ug\nyoutube aaaaaaaaaaa\n", encoding="utf-8")
        [video] = scan_library(out)
        self.assertEqual((video["title"], video["channel"], video["size"]), ("Clip", "Kênh A", 10))
        delete_video(video, out)
        self.assertEqual(scan_library(out), [])
        self.assertEqual((out / ".da-tai.txt").read_text(encoding="utf-8"), "youtube aaaaaaaaaaa\n")


if __name__ == "__main__":
    unittest.main()


class Automation(unittest.TestCase):
    def test_slots_fire_once_within_grace(self):
        from datetime import datetime
        from automation import due_slots, next_slot, parse_slots

        self.assertEqual(parse_slots("8:00, 20h30 12.15 21h"), ["08:00", "12:15", "20:30", "21:00"])
        with self.assertRaises(ValueError):
            parse_slots("25:00")
        now = datetime(2026, 11, 3, 8, 10)
        self.assertEqual(due_slots(["08:00", "12:00"], {}, now), ["08:00"])
        self.assertEqual(due_slots(["08:00"], {"08:00": "2026-11-03"}, now), [])
        self.assertEqual(due_slots(["07:00"], {}, now), [])  # quá 30 phút: không đăng bù
        self.assertEqual(next_slot(["08:00", "12:00"], {"08:00": "2026-11-03"}, now), datetime(2026, 11, 3, 12, 0))
        self.assertEqual(next_slot(["07:00"], {}, now), datetime(2026, 11, 4, 7, 0))

    def test_pick_skips_posted_and_uncertain(self):
        from automation import pick_video

        pages = [{"url": "p1"}, {"url": "p2"}]
        lib = [{"id": "a", "modified": 1}, {"id": "b", "modified": 2}]
        posts = {"a|p1": {"state": "posted"}, "a|p2": {"state": "uncertain"}}
        self.assertEqual(pick_video(lib, pages, posts)["id"], "b")
        posts.update({"b|p1": {"state": "failed", "fails": 2}, "b|p2": {"state": "posted"}})
        self.assertIsNone(pick_video(lib, pages, posts))
        posts["b|p1"]["fails"] = 1
        self.assertEqual(pick_video(lib, pages, posts)["id"], "b")

    def test_pages_and_caption(self):
        from automation import caption_for, parse_pages

        self.assertEqual(parse_pages("Hà Huệ | https://www.facebook.com/profile.php?id=1\n# tắt\n"),
                         [{"name": "Hà Huệ", "url": "https://www.facebook.com/profile.php?id=1"}])
        with self.assertRaises(ValueError):
            parse_pages("Hà Huệ")
        self.assertEqual(caption_for("{title}\n\n\n{hashtags}", "T", "#a", "u"), "T\n\n#a")

    def test_keywords(self):
        from automation import parse_keywords

        self.assertEqual(parse_keywords(" tin tức, bóng đá\ntin tức,, "), ["tin tức", "bóng đá"])
        with self.assertRaises(ValueError):
            parse_keywords("x" * 101)
