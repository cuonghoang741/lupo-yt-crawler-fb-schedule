"""Tab Facebook & Tự động: đăng nhập, Page, kênh tự cào, khung giờ, nội dung, nhật ký đăng."""
from __future__ import annotations

import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

import automation

STATES = {
    "posted": "Đã đăng",
    "uncertain": "Cần kiểm tra",
    "posting": "Đang đăng",
    "preparing": "Đang chuẩn bị",
    "failed": "Lỗi",
}


class AutoTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.store = automation.Store()
        self.engine = automation.Engine(self.store, lambda: app.snapshot, lambda k, v: app.events.put(("auto", k, v)))
        data = self.store.data

        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(0, 12))
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True)

        account = ttk.LabelFrame(left, text="Tài khoản Facebook", padding=8)
        account.pack(fill="x")
        self.account_label = ttk.Label(account, wraplength=330)
        self.account_label.pack(anchor="w")
        row = ttk.Frame(account)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Đăng nhập Facebook", command=self.login).pack(side="left")
        ttk.Button(row, text="Kiểm tra", command=lambda: self.engine.commands.put(("check_account",))).pack(side="left", padx=6)

        ttk.Label(left, text="Page đăng (mỗi dòng: Tên Page | link Page)").pack(anchor="w", pady=(10, 0))
        self.pages = tk.Text(left, height=4, width=46, wrap="none")
        self.pages.insert("1.0", "\n".join(f"{p['name']} | {p['url']}" for p in data["pages"]))
        self.pages.pack(fill="x")
        ttk.Label(left, text="Kênh YouTube tự cào (mỗi dòng một link kênh)").pack(anchor="w", pady=(8, 0))
        self.channels = tk.Text(left, height=3, width=46, wrap="none")
        self.channels.insert("1.0", "\n".join(data["channels"]))
        self.channels.pack(fill="x")
        ttk.Label(left, text="Khung giờ đăng mỗi ngày").pack(anchor="w", pady=(8, 0))
        self.slots = tk.StringVar(value=", ".join(data["slots"]))
        ttk.Entry(left, textvariable=self.slots).pack(fill="x")
        ttk.Label(left, text="Nội dung bài ({title}, {hashtags}, {sourceUrl})").pack(anchor="w", pady=(8, 0))
        self.caption = tk.Text(left, height=4, width=46, wrap="word")
        self.caption.insert("1.0", data["caption"])
        self.caption.pack(fill="x")
        ttk.Label(left, text="Hashtag").pack(anchor="w", pady=(8, 0))
        self.hashtags = tk.StringVar(value=data["hashtags"])
        ttk.Entry(left, textvariable=self.hashtags).pack(fill="x")
        ttk.Label(left, text="Từ khóa đọc tin (cách nhau bằng dấu phẩy)").pack(anchor="w", pady=(8, 0))
        self.keywords = tk.StringVar(value=", ".join(data["keywords"]))
        ttk.Entry(left, textvariable=self.keywords).pack(fill="x")
        self.reading = tk.BooleanVar(value=data["reading"])
        ttk.Checkbutton(left, text="Đọc tin mỗi giờ: tìm 1 từ khóa, cuộn đọc ~1 phút", variable=self.reading).pack(anchor="w", pady=(6, 0))
        self.show_browser = tk.BooleanVar(value=data["show_browser"])
        ttk.Checkbutton(left, text="Hiện trình duyệt khi bot chạy (để gỡ lỗi)", variable=self.show_browser).pack(anchor="w", pady=(4, 0))
        self.enabled = tk.BooleanVar(value=data["enabled"])
        ttk.Checkbutton(left, text="Bật tự cào (15 phút/lần) và tự đăng theo khung giờ", variable=self.enabled).pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(left)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Lưu cài đặt", command=self.save).pack(side="left")
        ttk.Button(row, text="Quét kênh ngay", command=lambda: self.save() and self.engine.commands.put(("scan_now",))).pack(side="left", padx=6)
        ttk.Button(row, text="Đăng 1 video ngay", command=self.post_now).pack(side="left")
        ttk.Button(left, text="Đọc tin ngay", command=lambda: self.save() and self.engine.commands.put(("read_now",))).pack(anchor="w", pady=(6, 0))
        self.next_label = ttk.Label(left, foreground="#555", wraplength=330)
        self.next_label.pack(anchor="w", pady=(10, 0))
        ttk.Label(left, text="Máy phải bật và mở app này thì mới tự cào/đăng.", foreground="#555", wraplength=330).pack(anchor="w", pady=(4, 0))

        ttk.Label(right, text="Bài đăng").pack(anchor="w")
        columns = ("at", "title", "page", "state", "url")
        self.posts = ttk.Treeview(right, columns=columns, show="headings", height=12)
        for key, text, width in [("at", "Thời gian", 120), ("title", "Video", 300), ("page", "Page", 130), ("state", "Trạng thái", 110), ("url", "Link / lỗi", 300)]:
            self.posts.heading(key, text=text)
            self.posts.column(key, width=width, stretch=key in ("title", "url"))
        self.posts.tag_configure("uncertain", foreground="#b26a00")
        self.posts.tag_configure("failed", foreground="#b00020")
        self.posts.tag_configure("posted", foreground="#1b7f3b")
        self.posts.pack(fill="both", expand=True)
        row = ttk.Frame(right)
        row.pack(fill="x", pady=6)
        ttk.Button(row, text="Mở link bài", command=self.open_post).pack(side="left")
        ttk.Button(row, text="Tìm lại bài trên Page", command=self.lookup).pack(side="left", padx=6)
        ttk.Button(row, text="Đánh dấu đã đăng…", command=self.mark_posted).pack(side="left")
        ttk.Button(row, text="Cho phép đăng lại", command=self.allow_retry).pack(side="left", padx=6)
        ttk.Label(right, text="Nhật ký").pack(anchor="w")
        self.log = tk.Text(right, height=9, state="disabled", wrap="word", foreground="#333")
        self.log.pack(fill="both")

        self.engine.start()
        self.render()
        self.after(30_000, self.tick)

    # ---------- sự kiện từ engine (đã về luồng giao diện) ----------
    def on_event(self, kind, value):
        if kind == "log":
            self.log.configure(state="normal")
            self.log.insert("end", value + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        elif kind == "status":
            self.app.status.set(value)
        elif kind == "library":
            self.app.refresh_library()
        self.render()

    def tick(self):
        self.render_next()
        self.after(30_000, self.tick)

    def render(self):
        data = self.store.data
        account = data.get("account")
        if not account:
            text = "Chưa đăng nhập. Bấm Đăng nhập Facebook, đăng nhập trong cửa sổ vừa mở rồi đóng cửa sổ đó."
        elif account.get("ok"):
            text = f"Đã đăng nhập: {account.get('name') or account.get('id')} (kiểm tra lúc {account['checked_at'].replace('T', ' ')})"
        else:
            text = "Facebook cần đăng nhập/xác minh lại. Bấm Đăng nhập Facebook."
        self.account_label.configure(text=text, foreground="#1b7f3b" if account and account.get("ok") else "#b26a00")
        selected = self.posts.selection()
        self.posts.delete(*self.posts.get_children())
        rows = sorted(data["posts"].items(), key=lambda kv: kv[1].get("at") or "", reverse=True)
        for key, post in rows[:300]:
            state = post.get("state", "")
            self.posts.insert("", "end", iid=key, tags=(state,), values=(
                (post.get("at") or "").replace("T", " "), post.get("title", ""), post.get("page", ""),
                STATES.get(state, state), post.get("url") or post.get("error") or ""))
        keep = [k for k in selected if self.posts.exists(k)]
        if keep:
            self.posts.selection_set(keep)
        self.render_next()

    def render_next(self):
        data = self.store.data
        at = automation.next_slot(data["slots"], data["fired"], datetime.now()) if data["enabled"] else None
        text = f"Lượt đăng tiếp theo: {at:%H:%M %d/%m}." if at else ("Chưa có khung giờ." if data["enabled"] else "Tự đăng đang tắt.")
        if data["reading"]:
            read_at = datetime.fromtimestamp(max(data["last_read"] + automation.READ_EVERY, time.time()))
            text += f" Đọc tin tiếp: {read_at:%H:%M}."
        self.next_label.configure(text=text)

    # ---------- thao tác ----------
    def save(self) -> bool:
        try:
            pages = automation.parse_pages(self.pages.get("1.0", "end"))
            slots = automation.parse_slots(self.slots.get())
            keywords = automation.parse_keywords(self.keywords.get())
            import ytcore
            channels = []
            for line in self.channels.get("1.0", "end").splitlines():
                if line.strip():
                    item = ytcore.youtube_input(line)
                    if item.kind != "channel":
                        raise ValueError(f"“{line.strip()}” không phải link kênh.")
                    channels.append(item.url)
        except ValueError as e:
            messagebox.showerror("Cài đặt chưa đúng", str(e))
            return False
        if self.enabled.get() and not (pages and slots):
            messagebox.showerror("Cài đặt chưa đúng", "Cần ít nhất một Page và một khung giờ để bật tự động.")
            return False
        if self.reading.get() and not keywords:
            messagebox.showerror("Cài đặt chưa đúng", "Cần ít nhất một từ khóa để bật đọc tin.")
            return False
        with self.store.lock:
            self.store.data.update(pages=pages, slots=slots, channels=channels, caption=self.caption.get("1.0", "end").strip(),
                                   hashtags=self.hashtags.get().strip(), enabled=self.enabled.get(),
                                   keywords=keywords, reading=self.reading.get(), show_browser=self.show_browser.get())
            self.store.save()
        self.app.status.set("Đã lưu cài đặt tự động.")
        self.render()
        return True

    def login(self):
        if self.engine.busy:
            return messagebox.showinfo("Đăng nhập", "Đang chạy tác vụ khác, đợi xong rồi đăng nhập.")
        self.engine.commands.put(("login",))

    def post_now(self):
        if not self.save():
            return
        if not self.store.data["pages"]:
            return messagebox.showinfo("Đăng ngay", "Thêm Page trước.")
        if messagebox.askyesno("Đăng ngay", "Đăng video cũ nhất chưa đăng trong Thư viện lên các Page ngay bây giờ?"):
            self.engine.commands.put(("post_now",))

    def selected(self):
        keys = self.posts.selection()
        if not keys:
            messagebox.showinfo("Bài đăng", "Chọn một dòng trước.")
            return None, None
        return keys[0], self.store.data["posts"][keys[0]]

    def open_post(self):
        key, post = self.selected()
        if post and post.get("url"):
            webbrowser.open(post["url"])

    def lookup(self):
        key, post = self.selected()
        if post:
            self.engine.commands.put(("lookup", key))

    def mark_posted(self):
        key, post = self.selected()
        if not post:
            return
        url = simpledialog.askstring("Đánh dấu đã đăng", "Dán link bài trên Page:", parent=self)
        if url and url.startswith("https://") and "facebook.com" in url:
            self.store.set_post(key, state="posted", url=url.strip(), error=None)
            self.render()

    def allow_retry(self):
        key, post = self.selected()
        if not post or post.get("state") not in ("uncertain", "failed"):
            return
        if post["state"] == "uncertain" and not messagebox.askyesno(
                "Cho phép đăng lại", "Bạn đã mở Page và chắc chắn bài này CHƯA lên? Đăng lại có thể bị trùng."):
            return
        self.store.set_post(key, state="failed", fails=0, error="Chờ đăng lại ở khung giờ tới.")
        self.render()

    def shutdown(self):
        self.engine.stop_event.set()
