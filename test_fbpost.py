"""Kiểm thử luồng đăng trên trang giả lập cục bộ: không có request nào tới Facebook thật."""
import tempfile
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # chưa cài playwright
    sync_playwright = None

import fbpost

COMPOSER = """<input id="cover" type="file" accept="image/*"><button id="photo">Photo/video</button>
<div role="dialog" id="compose" hidden><input type="file"><div role="textbox" contenteditable="true"></div><button id="post">Post</button></div>
<div id="result"></div>
<script>
document.getElementById('photo').onclick = () => { document.getElementById('compose').hidden = false; };
document.getElementById('post').onclick = () => {
  if (!window.persisted) throw Error('missing durable marker');
  const a = document.createElement('a'); a.href = 'https://www.facebook.com/123/posts/456'; a.textContent = 'View post';
  document.getElementById('result').appendChild(a);
};
</script>"""

REEL = """<button id="photo">Ảnh/video</button>
<div role="dialog" id="compose" hidden><input type="file" accept="video/*"><div contenteditable="true"></div><button id="bg">Tiếp</button></div>
<div role="dialog" id="edit" hidden><p>Chỉnh sửa thước phim</p><button id="next">Tiếp</button></div>
<div role="dialog" id="details" hidden><textarea></textarea><button id="share">Đăng</button></div><div id="result"></div>
<script>
window.bgClicks = 0;
document.getElementById('photo').onclick = () => { compose.hidden = false; edit.hidden = false; };
document.getElementById('bg').onclick = () => window.bgClicks++;
document.getElementById('next').onclick = () => { edit.hidden = true; details.hidden = false; };
document.getElementById('share').onclick = () => {
  const a = document.createElement('a'); a.href = 'https://www.facebook.com/reel/987'; a.textContent = 'Xem thước phim';
  result.appendChild(a);
};
</script>"""


@unittest.skipIf(sync_playwright is None, "cần playwright")
class Publish(unittest.TestCase):
    def run_fixture(self, html, caption, before_click):
        video = Path(tempfile.mkdtemp()) / "sample.mp4"
        video.write_bytes(b"local fixture")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html))
            page.goto("https://www.facebook.com/123")
            session = fbpost.Session.wrap(browser.contexts[0], page)
            try:
                url = session.publish(str(video), caption, {"url": "https://www.facebook.com/123", "name": "P"}, "123",
                                      lambda: before_click(page))
                return url, page.evaluate("""() => ({
                    caption: (document.querySelector('textarea') || document.querySelector('[contenteditable]')).value
                        ?? document.querySelector('[contenteditable]').innerText,
                    cover: document.getElementById('cover')?.files.length ?? 0,
                    bg: window.bgClicks})""")
            finally:
                browser.close()

    def test_marks_submission_before_clicking_post(self):
        marked = []

        def before(page):
            marked.append(True)
            page.evaluate("window.persisted = true")

        url, state = self.run_fixture(COMPOSER, "Test caption #test", before)
        self.assertEqual(url, "https://www.facebook.com/123/posts/456")
        self.assertEqual(marked, [True])
        self.assertEqual(state["cover"], 0)  # không dùng ô ảnh bìa
        self.assertEqual(state["caption"], "Test caption #test")

    def test_vietnamese_reel_wizard(self):
        url, state = self.run_fixture(REEL, "Mô tả thước phim", lambda page: None)
        self.assertEqual(url, "https://www.facebook.com/reel/987")
        self.assertEqual(state["caption"], "Mô tả thước phim")
        self.assertEqual(state["bg"], 0)  # chỉ bấm Tiếp ở hộp thoại trên cùng

    def test_stops_when_marker_cannot_be_written(self):
        def fail(page):
            raise RuntimeError("không ghi được nhật ký")

        with self.assertRaisesRegex(RuntimeError, "không ghi được"):
            self.run_fixture(COMPOSER, "x", fail)


@unittest.skipIf(sync_playwright is None, "cần playwright")
class ReadFeed(unittest.TestCase):
    def run_read(self, html):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context()
            context.add_cookies([{"name": "c_user", "value": "1", "url": "https://www.facebook.com"}])
            page = context.new_page()
            urls = []
            page.route("**/*", lambda route: (urls.append(route.request.url),
                                              route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)))
            waits = []
            try:
                fbpost.Session.wrap(context, page).read_feed("tin tức", lambda s: waits.append(s) and False, pause=0)
                return urls[0], len(waits), page.evaluate("window.scrollY")
            finally:
                browser.close()

    def test_searches_keyword_and_scrolls(self):
        url, waits, scrolled = self.run_read('<div role="main" style="height:20000px">bài</div>')
        self.assertEqual(url, "https://www.facebook.com/search/posts/?q=tin%20t%E1%BB%A9c")
        self.assertEqual(waits, 6)
        self.assertGreater(scrolled, 0)

    def test_stops_on_checkpoint(self):
        with self.assertRaises(fbpost.AuthRequired):
            self.run_read('<div role="main"><form action="/checkpoint/1"></form></div>')


if __name__ == "__main__":
    unittest.main()
