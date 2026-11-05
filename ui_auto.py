"""Các màn hình tự động: Tổng quan, Kênh theo dõi, Tài khoản & Page, Lịch đăng, Lịch sử đăng, cài đặt Facebook."""
from __future__ import annotations

import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from tkinter import messagebox, simpledialog, ttk

import automation
import ui_theme as T
import ytcore

STATES = {
    "posted": "Đã đăng",
    "uncertain": "Cần kiểm tra",
    "posting": "Đang đăng",
    "preparing": "Đang chuẩn bị",
    "failed": "Lỗi",
}
STATE_TAGS = {"posted": "ok", "uncertain": "warn", "failed": "err", "posting": "next", "preparing": "next"}
ACTIVITY = {
    "login": "Đang chờ bạn đăng nhập trong cửa sổ Facebook…",
    "check": "Đang kiểm tra tài khoản Facebook…",
    "scan": "Đang quét kênh YouTube…",
    "post": "Đang đăng bài lên Facebook…",
    "read": "Đang đọc tin Facebook…",
    "lookup": "Đang tìm bài trên Page…",
}


class Automation:
    def __init__(self, app):
        self.app = app
        self.store = automation.Store()
        self.engine = automation.Engine(self.store, lambda: app.snapshot, lambda k, v: app.events.put(("auto", k, v)))
        self.was_logged_in = bool((self.store.data.get("account") or {}).get("ok"))

    def start(self):
        self.engine.start()
        self.render()
        self.app.after(1000, self.poll)
        self.app.after(30_000, self.tick)

    def shutdown(self):
        self.engine.stop_event.set()

    def update(self, **values):
        with self.store.lock:
            self.store.data.update(values)
            self.store.save()
        self.render()

    def command(self, *command):
        self.engine.commands.put(command)
        self.poll(repeat=False)

    # ---------- trạng thái chung ----------
    def steps(self) -> list[tuple]:
        """(màn hình, tiêu đề, mô tả, đã xong)."""
        d = self.store.data
        return [
            ("facebook", "Đăng nhập Facebook", "Đăng nhập một lần bằng tài khoản quản lý Page.",
             bool((d.get("account") or {}).get("ok"))),
            ("facebook", "Thêm Page sẽ đăng", "Mỗi video được đăng lên tất cả Page trong danh sách.", bool(d["pages"])),
            ("channels", "Thêm nguồn video YouTube",
             "Thêm kênh để tool tự tải video mới, hoặc tải video thủ công.", bool(d["channels"] or self.app.library)),
            ("schedule", "Chọn giờ đăng và nội dung bài", "Mặc định đăng lúc 08:00, 12:00 và 20:00.",
             bool(d.get("schedule_reviewed") or d["enabled"])),
            ("overview", "Bật tự động", "Tool tự tải video mới và tự đăng đúng giờ.", bool(d["enabled"])),
        ]

    def next_video(self) -> dict | None:
        d = self.store.data
        return automation.pick_video(self.app.library, d["pages"], d["posts"]) if d["pages"] else None

    def video_status(self, video: dict) -> tuple[str, str]:
        d = self.store.data
        if not d["pages"] or not video.get("id"):
            return "Chờ đăng", ""
        states = [(d["posts"].get(f"{video['id']}|{p['url']}") or {}).get("state") for p in d["pages"]]
        posted = states.count("posted")
        if "uncertain" in states:
            return "Cần kiểm tra", "warn"
        if posted == len(states):
            return "Đã đăng", "ok"
        if getattr(self, "_next_id", None) == video["id"]:
            return "Đăng tiếp theo", "next"
        if posted:
            return f"Đã đăng {posted}/{len(states)} Page", ""
        return "Chờ đăng", ""

    def poll(self, repeat=True):
        busy = ACTIVITY.get(self.engine.current or "")
        self.app.activity.configure(text=f"⏳ {busy}" if busy else "")
        self.login_button.configure(state="disabled" if self.engine.current == "login" else "normal")
        if repeat:
            self.app.after(1000, self.poll)

    def tick(self):
        self.render()
        self.app.after(30_000, self.tick)

    def on_event(self, kind, value):
        if kind == "log":
            self.log.configure(state="normal")
            self.log.insert("end", value + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
            self.app.status.set(value)
        elif kind == "status":
            self.app.status.set(value)
        elif kind == "library":
            return self.app.refresh_library()  # refresh_library tự gọi render
        self.render()

    def render(self):
        d = self.store.data
        nv = self.next_video()
        self._next_id = nv and nv["id"]
        steps = self.steps()
        self.render_overview(steps, nv)
        self.render_facebook()
        self.render_channels()
        self.render_history()
        self.render_schedule_state()

        logged_in = steps[0][3]
        nav = self.app.nav
        nav.set_mark("facebook", "✓" if logged_in and d["pages"] else "!" if d.get("account") and not logged_in else "",
                     "#4ADE80" if logged_in else "#FBBF24")
        nav.set_mark("channels", str(len(d["channels"])) if d["channels"] else "", "#9CA3AF")
        nav.set_mark("schedule", "✓" if steps[3][3] else "")
        waiting = sum(self.video_status(v)[1] in ("", "next") for v in self.app.library)
        nav.set_mark("library", str(waiting) if waiting else "", "#9CA3AF")
        check = sum(p.get("state") == "uncertain" for p in d["posts"].values())
        nav.set_mark("history", str(check) if check else "", "#FBBF24")
        nav.set_mark("overview", "● Bật" if d["enabled"] else "", "#4ADE80")

        if d.get("account") and not logged_in:
            self.app.set_banner("Facebook cần đăng nhập lại. Tool đã dừng đăng cho tới khi bạn đăng nhập.",
                                "Đăng nhập lại", lambda: (self.app.show("facebook"), self.login()))
        else:
            todo = next((i for i, s in enumerate(steps) if not s[3]), None)
            if todo is None:
                self.app.set_banner(None)
            else:
                key, title, desc, _ = steps[todo]
                action = self.toggle_enabled if todo == 4 else (lambda k=key: self.app.show(k))
                self.app.set_banner(f"Bước tiếp theo ({todo + 1}/5): {title}. {desc}",
                                    "Bật tự động" if todo == 4 else "Làm ngay →", action)
        just_logged_in = logged_in and not self.was_logged_in
        self.was_logged_in = logged_in
        if just_logged_in and not d["pages"]:  # vừa đăng nhập xong: đưa thẳng tới chỗ thêm Page
            self.app.show("facebook")
            self.page_name.focus_set()

    # ---------- Tổng quan ----------
    def build_overview(self, parent):
        page = T.Page(parent, "Tổng quan", "Tải video YouTube về máy rồi tự đăng lên Page Facebook theo giờ bạn đặt. "
                                          "Máy phải bật và mở tool thì mới chạy.")
        box = T.card(page)
        top = T.row(box)
        left = ttk.Frame(top, style="Card.TFrame")
        left.pack(side="left", fill="x", expand=True)
        self.ov_state = T.label(left, kind="big")
        self.ov_state.pack(anchor="w")
        self.ov_state_hint = T.label(left, kind="muted")
        self.ov_state_hint.pack(anchor="w", pady=(2, 0))
        self.ov_toggle = ttk.Button(top, command=self.toggle_enabled)
        self.ov_toggle.pack(side="right")
        ttk.Button(top, text="Đăng thử 1 video ngay", command=self.post_now).pack(side="right", padx=8)

        stats = T.row(box, pady=(14, 0))
        self.ov_stats = {}
        for i, (key, title) in enumerate([("next", "Lượt đăng tiếp theo"), ("video", "Video sẽ đăng"),
                                          ("library", "Kho video"), ("posted", "Đã đăng")]):
            cell = tk.Frame(stats, bg="#F9FAFB", highlightthickness=1, highlightbackground=T.BORDER)
            cell.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            stats.grid_columnconfigure(i, weight=2 if key == "video" else 1, uniform="s" if key != "video" else "")
            tk.Label(cell, text=title, bg="#F9FAFB", fg=T.MUTED, font=T.font(-1), anchor="w").pack(fill="x", padx=12, pady=(10, 0))
            value = tk.Label(cell, bg="#F9FAFB", fg=T.TEXT, font=T.font(2, "bold"), anchor="w", justify="left")
            value.pack(fill="x", padx=12, pady=(2, 10))
            value.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(120, e.width - 4)))
            self.ov_stats[key] = value

        box = T.card(page, "Các bước cài đặt (làm lần lượt từ trên xuống)")
        self.ov_steps = []
        for i in range(5):
            line = T.row(box, pady=(0, 4))
            badge = tk.Label(line, width=3, font=T.font(0, "bold"), pady=2)
            badge.pack(side="left")
            texts = ttk.Frame(line, style="Card.TFrame")
            texts.pack(side="left", fill="x", expand=True, padx=12)
            title = T.label(texts, kind="bold")
            title.pack(anchor="w")
            desc = T.label(texts, kind="muted")
            desc.pack(anchor="w")
            button = ttk.Button(line, text="Mở →")
            button.pack(side="right")
            self.ov_steps.append((badge, title, desc, button))
        return page

    def render_overview(self, steps, nv):
        d = self.store.data
        on = d["enabled"]
        self.ov_state.configure(text="● Tự động đang BẬT" if on else "○ Tự động đang TẮT",
                                foreground=T.GREEN if on else T.MUTED)
        self.ov_state_hint.configure(text="Tool đang tự tải video mới và tự đăng theo giờ." if on else
                                     "Chưa đăng gì tự động. Làm xong các bước bên dưới rồi bấm Bật tự động.")
        self.ov_toggle.configure(text="Tắt tự động" if on else "Bật tự động", style="TButton" if on else "Accent.TButton")
        at = automation.next_slot(d["slots"], d["fired"], datetime.now()) if on else None
        if at:
            day = "hôm nay" if at.date() == datetime.now().date() else \
                "ngày mai" if at.date() == datetime.now().date() + timedelta(days=1) else f"{at:%d/%m}"
            self.ov_stats["next"].configure(text=f"{at:%H:%M} {day}")
        else:
            self.ov_stats["next"].configure(text="Đang tắt" if not on else "Chưa có giờ")
        if not d["pages"]:
            video = "Chưa có Page"
        elif nv:
            video = nv["title"][:90]
        else:
            video = "Kho đã hết video chưa đăng"
        self.ov_stats["video"].configure(text=video)
        waiting = sum(self.video_status(v)[1] in ("", "next") for v in self.app.library)
        self.ov_stats["library"].configure(text=f"{waiting} chờ đăng / {len(self.app.library)}")
        posted = sum(p.get("state") == "posted" for p in d["posts"].values())
        check = sum(p.get("state") == "uncertain" for p in d["posts"].values())
        self.ov_stats["posted"].configure(text=f"{posted} bài" + (f" · {check} cần kiểm tra" if check else ""),
                                          fg=T.AMBER if check else T.TEXT)

        first_todo = next((i for i, s in enumerate(steps) if not s[3]), None)
        for i, ((key, title, desc, done), (badge, t, de, button)) in enumerate(zip(steps, self.ov_steps)):
            badge.configure(text="✓" if done else str(i + 1), bg=T.GREEN_SOFT if done else
                            (T.ACCENT if i == first_todo else "#F3F4F6"),
                            fg=T.GREEN if done else ("white" if i == first_todo else T.MUTED))
            t.configure(text=title, foreground=T.MUTED if done else T.TEXT)
            de.configure(text=desc)
            if i == 4:
                button.configure(text="Tắt tự động" if done else "Bật tự động", command=self.toggle_enabled)
            else:
                button.configure(text="Sửa" if done else "Làm ngay →", command=lambda k=key: self.app.show(k))
            button.configure(style="Small.Accent.TButton" if i == first_todo else "Small.TButton")

    def toggle_enabled(self):
        d = self.store.data
        if d["enabled"]:
            self.update(enabled=False)
            return self.app.status.set("Đã tắt tự động. Tool không tự tải và không tự đăng nữa.")
        if not d["pages"]:
            messagebox.showinfo("Bật tự động", "Thêm ít nhất một Page trước.")
            return self.app.show("facebook")
        if not d["slots"]:
            messagebox.showinfo("Bật tự động", "Chọn ít nhất một giờ đăng trước.")
            return self.app.show("schedule")
        if not (d.get("account") or {}).get("ok") and not messagebox.askyesno(
                "Bật tự động", "Facebook chưa đăng nhập nên tool chưa đăng được. Vẫn bật?"):
            return
        self.update(enabled=True)
        if d["channels"]:
            self.command("scan_now")
        self.app.status.set("Đã bật tự động.")

    def post_now(self):
        if not self.store.data["pages"]:
            messagebox.showinfo("Đăng thử", "Thêm Page trước.")
            return self.app.show("facebook")
        nv = self.next_video()
        if not nv:
            return messagebox.showinfo("Đăng thử", "Kho video không còn video nào chưa đăng. Thêm kênh hoặc tải video thủ công.")
        if messagebox.askyesno("Đăng thử", f"Đăng ngay video “{nv['title'][:80]}” lên {len(self.store.data['pages'])} Page?"):
            self.command("post_now")
            self.app.show("history")

    # ---------- Kênh theo dõi ----------
    def build_channels(self, parent):
        page = T.Page(parent, "Kênh YouTube theo dõi",
                      "Khi bật tự động, cứ 15 phút tool kiểm tra các kênh này và tải video MỚI về Kho video để chờ đăng. "
                      "Video cũ đã có trước khi thêm kênh sẽ không tải; muốn lấy video cũ thì dùng Tải thủ công.")
        box = T.card(page, "Thêm kênh", "Dán link kênh, ví dụ https://www.youtube.com/@tenkenh")
        bar = T.row(box)
        self.channel_entry = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.channel_entry)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.add_channel())
        ttk.Button(bar, text="+ Thêm kênh", style="Accent.TButton", command=self.add_channel).pack(side="left", padx=(8, 0))

        box = T.card(page, "Đang theo dõi", expand=True)
        self.channel_view = T.table(box, [("url", "Kênh", 460, "w", True), ("state", "Trạng thái", 240, "w", False)])
        bar = T.row(box)
        ttk.Button(bar, text="Bỏ theo dõi", command=self.remove_channel).pack(side="left")
        ttk.Button(bar, text="Quét ngay", command=lambda: self.command("scan_now")).pack(side="left", padx=8)
        self.channel_hint = T.label(bar, kind="muted")
        self.channel_hint.pack(side="right")
        return page

    def render_channels(self):
        d = self.store.data
        self.channel_view.delete(*self.channel_view.get_children())
        for url in d["channels"]:
            seen = d["seen"].get(url)
            state = f"Đang theo dõi · đã biết {len(seen)} video" if seen is not None else "Chờ quét lần đầu"
            self.channel_view.insert("", "end", iid=url, values=(url, state), tags=("ok" if seen is not None else "muted",))
        last = self.engine.last_scan
        auto = "Tự quét 15 phút/lần." if d["enabled"] else "Tự động đang tắt: chỉ quét khi bấm Quét ngay."
        self.channel_hint.configure(text=(f"Quét gần nhất {datetime.fromtimestamp(last):%H:%M}. " if last else "") + auto)

    def add_channel(self):
        try:
            item = ytcore.youtube_input(self.channel_entry.get())
        except ValueError as e:
            return messagebox.showerror("Link chưa đúng", str(e))
        if item.kind != "channel":
            return messagebox.showerror("Link chưa đúng", "Đây là link video. Dán link kênh (có @tên hoặc /channel/…), "
                                                          "hoặc tải video này ở mục Tải thủ công.")
        if item.url in self.store.data["channels"]:
            return messagebox.showinfo("Thêm kênh", "Kênh này đã có trong danh sách.")
        self.update(channels=self.store.data["channels"] + [item.url])
        self.channel_entry.set("")
        self.command("scan_now")  # lần đầu chỉ ghi mốc video cũ

    def remove_channel(self):
        keys = self.channel_view.selection()
        if not keys:
            return messagebox.showinfo("Bỏ theo dõi", "Chọn kênh trong danh sách trước.")
        self.update(channels=[c for c in self.store.data["channels"] if c not in keys])

    # ---------- Tài khoản & Page ----------
    def build_facebook(self, parent):
        page = T.Page(parent, "Tài khoản & Page")
        box = T.card(page, "1. Tài khoản Facebook")
        self.account_label = T.label(box, kind="bold", wrap=True)
        self.account_label.pack(fill="x")
        self.account_hint = T.label(box, kind="muted", wrap=True)
        self.account_hint.pack(fill="x", pady=(2, 10))
        bar = T.row(box)
        self.login_button = ttk.Button(bar, text="Đăng nhập Facebook", command=self.login)
        self.login_button.pack(side="left")
        ttk.Button(bar, text="Kiểm tra lại", command=lambda: self.command("check_account")).pack(side="left", padx=8)

        box = T.card(page, "2. Page sẽ đăng", "Mỗi video được đăng lên tất cả Page dưới đây. Tên Page phải giống tên hiển thị "
                                            "trên Facebook; link lấy trên thanh địa chỉ khi mở Page.", expand=True)
        form = T.row(box, pady=(0, 10))
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(3, weight=2)
        T.label(form, "Tên Page").grid(row=0, column=0, padx=(0, 6))
        self.page_name = ttk.Entry(form)
        self.page_name.grid(row=0, column=1, sticky="ew", padx=(0, 14))
        T.label(form, "Link Page").grid(row=0, column=2, padx=(0, 6))
        self.page_url = ttk.Entry(form)
        self.page_url.grid(row=0, column=3, sticky="ew")
        self.page_url.bind("<Return>", lambda e: self.add_page())
        ttk.Button(form, text="+ Thêm Page", style="Accent.TButton", command=self.add_page).grid(row=0, column=4, padx=(8, 0))
        self.page_view = T.table(box, [("name", "Tên Page", 220, "w", False), ("url", "Link", 420, "w", True)])
        bar = T.row(box)
        ttk.Button(bar, text="Xóa Page đã chọn", command=self.remove_page).pack(side="left")
        return page

    def render_facebook(self):
        d = self.store.data
        account = d.get("account")
        if self.engine.current == "login":
            text, kind = "Cửa sổ Facebook đang mở. Đăng nhập xong thì đóng cửa sổ đó.", "warn"
            hint = "Nếu Facebook hỏi mã xác minh, nhập ở cửa sổ đó. Tool không tự vượt xác minh."
        elif not account:
            text, kind = "Chưa đăng nhập", "warn"
            hint = ("Bấm Đăng nhập Facebook. Một cửa sổ trình duyệt sẽ mở: đăng nhập tài khoản quản lý Page, "
                    "rồi đóng cửa sổ đó. Tool tự kiểm tra và chỉ cần làm một lần.")
        elif account.get("ok"):
            text, kind = f"✓ Đã đăng nhập: {account.get('name') or account.get('id')}", "ok"
            hint = (f"Kiểm tra lúc {account['checked_at'].replace('T', ' ')}. "
                    + ("Bước tiếp theo: thêm Page ở bên dưới." if not d["pages"] else
                       "Xong phần này. Tiếp theo: Lịch đăng & nội dung."))
        else:
            text, kind = "Facebook cần đăng nhập hoặc xác minh lại", "err"
            hint = "Bấm Đăng nhập Facebook, đăng nhập lại trong cửa sổ mở ra rồi đóng cửa sổ đó."
        self.account_label.configure(text=text, style=f"Card.{kind}.TLabel")
        self.account_hint.configure(text=hint)
        self.login_button.configure(style="TButton" if account and account.get("ok") else "Accent.TButton")
        self.page_view.delete(*self.page_view.get_children())
        for p in d["pages"]:
            self.page_view.insert("", "end", iid=p["url"], values=(p["name"], p["url"]))

    def login(self):
        if self.engine.busy:
            return messagebox.showinfo("Đăng nhập", "Bot đang làm việc khác, đợi xong rồi đăng nhập.")
        self.command("login")
        self.render()

    def add_page(self):
        name, url = self.page_name.get().strip(), self.page_url.get().strip()
        if not name:
            return messagebox.showerror("Thêm Page", "Nhập tên Page.")
        try:
            page = automation.parse_pages(f"{name} | {url}")[0]
        except ValueError:
            return messagebox.showerror("Thêm Page", "Link Page phải bắt đầu bằng https://www.facebook.com/…")
        if any(p["url"] == page["url"] for p in self.store.data["pages"]):
            return messagebox.showinfo("Thêm Page", "Page này đã có trong danh sách.")
        self.update(pages=self.store.data["pages"] + [page])
        self.page_name.delete(0, "end")
        self.page_url.delete(0, "end")

    def remove_page(self):
        keys = self.page_view.selection()
        if not keys:
            return messagebox.showinfo("Xóa Page", "Chọn Page trong danh sách trước.")
        pages = [p for p in self.store.data["pages"] if p["url"] not in keys]
        if self.store.data["enabled"] and not pages:
            return messagebox.showerror("Xóa Page", "Đang bật tự động nên cần giữ ít nhất một Page. Tắt tự động trước.")
        self.update(pages=pages)

    # ---------- Lịch đăng & nội dung ----------
    def build_schedule(self, parent):
        d = self.store.data
        page = T.Page(parent, "Lịch đăng & nội dung")
        box = T.card(page, "Giờ đăng mỗi ngày", "Mỗi khung giờ tool đăng 1 video (cũ nhất chưa đăng trong Kho) lên tất cả Page. "
                                              "Cách nhau bằng dấu phẩy, ví dụ: 08:00, 12:00, 20h")
        self.slots = tk.StringVar(value=", ".join(d["slots"]))
        ttk.Entry(box, textvariable=self.slots).pack(fill="x")

        box = T.card(page, "Nội dung bài đăng",
                     "Chữ trong ngoặc nhọn được thay tự động: {title} = tiêu đề video, {hashtags} = hashtag bên dưới, "
                     "{sourceUrl} = link YouTube gốc.")
        self.caption = T.text_box(box, 4)
        self.caption.insert("1.0", d["caption"])
        self.caption.pack(fill="x")
        self.caption.bind("<KeyRelease>", lambda e: self.render_preview())
        T.label(box, "Hashtag", "bold").pack(anchor="w", pady=(10, 4))
        self.hashtags = tk.StringVar(value=d["hashtags"])
        self.hashtags.trace_add("write", lambda *a: self.render_preview())
        ttk.Entry(box, textvariable=self.hashtags).pack(fill="x")
        T.label(box, "Xem trước", "bold").pack(anchor="w", pady=(10, 4))
        self.preview = tk.Label(box, bg="#F9FAFB", fg=T.TEXT, font=T.font(), justify="left", anchor="nw", padx=10, pady=8,
                                highlightthickness=1, highlightbackground=T.BORDER)
        self.preview.pack(fill="x")
        self.preview.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(200, e.width - 24)))

        bar = ttk.Frame(page)
        bar.pack(fill="x")
        ttk.Button(bar, text="Lưu lịch đăng", style="Accent.TButton", command=self.save_schedule).pack(side="left")
        self.schedule_state = T.label(bar, kind="muted", card=False)
        self.schedule_state.pack(side="left", padx=12)
        self.render_preview()
        return page

    def render_preview(self):
        nv = self.next_video() if hasattr(self, "_next_id") else None
        title = nv["title"] if nv else "Tiêu đề video mẫu"
        url = (nv or {}).get("url") or "https://www.youtube.com/watch?v=…"
        self.preview.configure(text=automation.caption_for(self.caption.get("1.0", "end"), title, self.hashtags.get().strip(), url)
                               or "(bài đăng trống)")

    def render_schedule_state(self):
        on = self.store.data["enabled"]
        if not getattr(self, "schedule_saved_at", None):
            self.schedule_state.configure(text="Tự động đang bật." if on else "Tự động đang tắt — bật ở Tổng quan.")

    def save_schedule(self):
        try:
            slots = automation.parse_slots(self.slots.get())
        except ValueError as e:
            return messagebox.showerror("Giờ đăng chưa đúng", str(e))
        if not slots:
            return messagebox.showerror("Giờ đăng chưa đúng", "Cần ít nhất một giờ đăng.")
        caption = self.caption.get("1.0", "end").strip()
        if not caption:
            return messagebox.showerror("Nội dung bài", "Nội dung bài không được trống. Dùng {title} để lấy tiêu đề video.")
        self.slots.set(", ".join(slots))
        self.update(slots=slots, caption=caption, hashtags=self.hashtags.get().strip(), schedule_reviewed=True)
        self.schedule_saved_at = datetime.now()
        self.schedule_state.configure(text=f"✓ Đã lưu lúc {self.schedule_saved_at:%H:%M}.", foreground=T.GREEN)

    # ---------- Lịch sử đăng ----------
    def build_history(self, parent):
        page = T.Page(parent, "Lịch sử đăng",
                      "“Cần kiểm tra” nghĩa là tool đã bấm Đăng nhưng chưa lấy được link bài. Tool không tự đăng lại để tránh trùng: "
                      "bấm Tìm lại bài, hoặc mở Page xem rồi chọn Đánh dấu đã đăng / Cho phép đăng lại.")
        box = T.card(page, expand=True)
        self.posts = T.table(box, [("at", "Thời gian", 125, "w", False), ("title", "Video", 230, "w", True),
                                   ("page", "Page", 120, "w", False), ("state", "Trạng thái", 100, "w", False),
                                   ("url", "Link bài / lỗi", 210, "w", True)])
        bar = T.row(box)
        ttk.Button(bar, text="Mở link bài", command=self.open_post).pack(side="left")
        ttk.Button(bar, text="Tìm lại bài trên Page", command=self.lookup).pack(side="left", padx=8)
        ttk.Button(bar, text="Đánh dấu đã đăng…", command=self.mark_posted).pack(side="left")
        ttk.Button(bar, text="Cho phép đăng lại", command=self.allow_retry).pack(side="left", padx=8)

        box = T.card(page, "Nhật ký bot", pady=(0, 0))
        self.log = T.text_box(box, 5)
        self.log.configure(state="disabled", fg="#374151", font=T.font(-1))
        self.log.pack(fill="both", expand=True)
        return page

    def render_history(self):
        selected = self.posts.selection()
        self.posts.delete(*self.posts.get_children())
        rows = sorted(self.store.data["posts"].items(), key=lambda kv: kv[1].get("at") or "", reverse=True)
        for key, post in rows[:300]:
            state = post.get("state", "")
            self.posts.insert("", "end", iid=key, tags=(STATE_TAGS.get(state, ""),), values=(
                (post.get("at") or "").replace("T", " "), post.get("title", ""), post.get("page", ""),
                STATES.get(state, state), post.get("url") or post.get("error") or ""))
        keep = [k for k in selected if self.posts.exists(k)]
        if keep:
            self.posts.selection_set(keep)

    def selected(self):
        keys = self.posts.selection()
        if not keys:
            messagebox.showinfo("Lịch sử đăng", "Chọn một bài trong danh sách trước.")
            return None, None
        return keys[0], self.store.data["posts"][keys[0]]

    def open_post(self):
        key, post = self.selected()
        if post and post.get("url"):
            webbrowser.open(post["url"])
        elif post:
            messagebox.showinfo("Mở link bài", "Bài này chưa có link.")

    def lookup(self):
        key, post = self.selected()
        if post:
            self.command("lookup", key)

    def mark_posted(self):
        key, post = self.selected()
        if not post:
            return
        url = simpledialog.askstring("Đánh dấu đã đăng", "Dán link bài trên Page:", parent=self.app)
        if url and url.strip().startswith("https://") and "facebook.com" in url:
            self.store.set_post(key, state="posted", url=url.strip(), error=None)
            self.render()
        elif url:
            messagebox.showerror("Đánh dấu đã đăng", "Link phải là link bài Facebook (https://…facebook.com/…).")

    def allow_retry(self):
        key, post = self.selected()
        if not post:
            return
        if post.get("state") not in ("uncertain", "failed"):
            return messagebox.showinfo("Cho phép đăng lại", "Chỉ dùng cho bài Cần kiểm tra hoặc Lỗi.")
        if post["state"] == "uncertain" and not messagebox.askyesno(
                "Cho phép đăng lại", "Bạn đã mở Page và chắc chắn bài này CHƯA lên? Đăng lại có thể bị trùng."):
            return
        self.store.set_post(key, state="failed", fails=0, error="Chờ đăng lại ở khung giờ tới.")
        self.render()

    # ---------- Cài đặt Facebook nâng cao ----------
    def build_settings(self, page):
        d = self.store.data
        box = T.card(page, "Facebook nâng cao", "Không bắt buộc.")
        self.reading = tk.BooleanVar(value=d["reading"])
        ttk.Checkbutton(box, text="Đọc tin mỗi giờ cho giống người dùng thật: tìm 1 từ khóa, cuộn đọc khoảng 1 phút",
                        variable=self.reading).pack(anchor="w")
        bar = T.row(box, pady=(6, 0))
        T.label(bar, "Từ khóa (cách nhau bằng dấu phẩy)").pack(side="left")
        self.keywords = tk.StringVar(value=", ".join(d["keywords"]))
        ttk.Entry(bar, textvariable=self.keywords).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(bar, text="Đọc tin ngay", command=lambda: self.save_advanced() and self.command("read_now")).pack(side="left")
        self.show_browser = tk.BooleanVar(value=d["show_browser"])
        ttk.Checkbutton(box, text="Hiện trình duyệt khi bot chạy (chỉ bật khi cần gỡ lỗi, đừng thao tác vào cửa sổ đó)",
                        variable=self.show_browser).pack(anchor="w", pady=(10, 0))
        bar = T.row(box, pady=(12, 0))
        ttk.Button(bar, text="Lưu", style="Accent.TButton", command=self.save_advanced).pack(side="left")
        self.advanced_state = T.label(bar, kind="muted")
        self.advanced_state.pack(side="left", padx=12)

    def save_advanced(self) -> bool:
        try:
            keywords = automation.parse_keywords(self.keywords.get())
        except ValueError as e:
            messagebox.showerror("Từ khóa chưa đúng", str(e))
            return False
        if self.reading.get() and not keywords:
            messagebox.showerror("Từ khóa chưa đúng", "Cần ít nhất một từ khóa để bật đọc tin.")
            return False
        self.update(keywords=keywords, reading=self.reading.get(), show_browser=self.show_browser.get())
        self.advanced_state.configure(text=f"✓ Đã lưu lúc {datetime.now():%H:%M}.", foreground=T.GREEN)
        return True

