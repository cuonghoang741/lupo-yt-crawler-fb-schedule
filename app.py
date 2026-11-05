"""YouTube → Facebook cho Windows: menu trái theo từng bước, tải video YouTube về Kho video rồi tự đăng lên Page."""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import ui_theme as T
import ytcore

SETTINGS = ytcore.app_dir() / "settings.json"
QUALITIES = {"1080p": 1080, "720p": 720, "480p": 480, "360p": 360}
POST_FILTERS = ["Tất cả trạng thái", "Chờ đăng", "Đã đăng", "Cần kiểm tra"]


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def open_path(path: str) -> None:
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - mở file người dùng chọn
    else:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", path], check=False)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("YouTube → Facebook")
        self.geometry("1180x740")
        self.minsize(980, 620)
        self.configure(bg=T.BG)
        T.apply(self)
        settings = load_settings()
        self.output = tk.StringVar(value=settings.get("output") or str(Path.home() / "Videos" / "YouTube"))
        self.quality = tk.StringVar(value=settings.get("quality") or "1080p")
        self.events: queue.Queue = queue.Queue()
        self.jobs: list[dict] = []  # {iid, url, title, channel, status}
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        self.tools: dict | None = None
        self.library: list[dict] = []
        self.shown: dict[str, dict] = {}
        # Luồng nền đọc bản sao này thay vì biến Tk.
        self.snapshot = (Path(self.output.get()), QUALITIES[self.quality.get()])
        for var in (self.output, self.quality):
            var.trace_add("write", lambda *a: self.update_snapshot())
        self.quality.trace_add("write", lambda *a: self.save_settings())

        self.nav = T.Sidebar(self, self.show)
        self.nav.pack(side="left", fill="y")
        main = ttk.Frame(self)
        main.pack(side="left", fill="both", expand=True)

        # Dải "Bước tiếp theo" luôn nằm trên cùng cho tới khi cài đặt xong.
        self.banner = tk.Frame(main, bg=T.ACCENT_SOFT, highlightthickness=1, highlightbackground="#C7D7FE")
        self.banner_text = tk.Label(self.banner, bg=T.ACCENT_SOFT, fg=T.ACCENT_DARK, font=T.font(0, "bold"), anchor="w")
        self.banner_text.pack(side="left", fill="x", expand=True, padx=(16, 8), pady=10)
        self.banner_button = ttk.Button(self.banner, style="Accent.TButton")
        self.banner_button.pack(side="right", padx=12, pady=6)

        bar = tk.Frame(main, bg=T.CARD, highlightthickness=1, highlightbackground=T.BORDER)
        bar.pack(fill="x", side="bottom")
        self.status = tk.StringVar(value="Sẵn sàng.")
        tk.Label(bar, textvariable=self.status, bg=T.CARD, fg=T.MUTED, font=T.font(-1), anchor="w").pack(
            side="left", fill="x", expand=True, padx=16, pady=6)
        self.activity = tk.Label(bar, text="", bg=T.CARD, fg=T.ACCENT, font=T.font(-1, "bold"))
        self.activity.pack(side="right", padx=16)
        self.stack = ttk.Frame(main)
        self.stack.pack(fill="both", expand=True)
        self.stack.grid_rowconfigure(0, weight=1)
        self.stack.grid_columnconfigure(0, weight=1)

        import ui_auto

        self.auto = ui_auto.Automation(self)
        self.pages: dict[str, ttk.Frame] = {}
        layout = [
            ("Bắt đầu", [("overview", "Tổng quan", self.auto.build_overview)]),
            ("YouTube", [("channels", "Kênh theo dõi", self.auto.build_channels),
                         ("download", "Tải thủ công", self.build_download),
                         ("library", "Kho video", self.build_library),
                         ("downloads", "Lịch sử tải", self.auto.build_downloads)]),
            ("Facebook", [("facebook", "Tài khoản & Page", self.auto.build_facebook),
                          ("schedule", "Lịch đăng & nội dung", self.auto.build_schedule),
                          ("history", "Lịch sử đăng", self.auto.build_history)]),
            ("Khác", [("settings", "Cài đặt", self.build_settings)]),
        ]
        for group, items in layout:
            self.nav.group(group)
            for key, text, build in items:
                self.nav.item(key, text)
                page = build(self.stack)
                page.grid(row=0, column=0, sticky="nsew")
                self.pages[key] = page

        self.refresh_library()
        self.auto.start()
        self.show("overview")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.pump)

    def show(self, key: str) -> None:
        self.current_page = key
        self.pages[key].tkraise()
        self.nav.set_active(key)
        if key in ("library", "overview"):
            self.refresh_library()
        self.auto.render()

    def set_banner(self, text: str | None, button: str = "", command=None) -> None:
        if not text:
            self.banner.pack_forget()
            return
        self.banner_text.configure(text=text)
        self.banner_button.configure(text=button, command=command)
        if not self.banner.winfo_ismapped():
            self.banner.pack(fill="x", before=self.stack, padx=28, pady=(16, 0))

    # ---------- Tải thủ công ----------
    def build_download(self, parent) -> ttk.Frame:
        page = T.Page(parent, "Tải video thủ công",
                      "Dán link video, hoặc link kênh để tải toàn bộ video của kênh đó. Video tải xong nằm trong "
                      "Kho video và sẽ được đăng lên Page theo lịch khi bạn bật tự động.")
        box = T.card(page, "Link YouTube", "Mỗi dòng một link. Có thể nhập nhiều link từ file CSV/TXT.")
        self.links = T.text_box(box, 4, wrap="none")
        self.links.pack(fill="x", pady=(0, 10))
        bar = T.row(box)
        self.start_button = ttk.Button(bar, text="⬇  Tải về Kho video", style="Accent.TButton", command=self.start_from_text)
        self.start_button.pack(side="left")
        ttk.Button(bar, text="Nhập từ file…", command=self.import_file).pack(side="left", padx=8)
        self.stop_button = ttk.Button(bar, text="Dừng", command=self.request_stop, state="disabled")
        self.stop_button.pack(side="left")
        self.output_hint = T.label(bar, kind="muted")
        self.output_hint.pack(side="right")

        box = T.card(page, "Hàng đợi tải", expand=True)
        self.queue_view = T.table(box, [
            ("title", "Video", 320, "w", True), ("channel", "Kênh", 140, "w", False),
            ("status", "Trạng thái", 180, "w", False), ("progress", "Tiến độ", 70, "e", False),
            ("size", "Dung lượng", 80, "e", False)])
        bar = T.row(box)
        self.overall = ttk.Progressbar(bar, mode="determinate")
        self.overall.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ttk.Button(bar, text="Thử lại video lỗi", command=self.retry_failed).pack(side="left")
        ttk.Button(bar, text="Dọn video đã xong", command=self.clear_done).pack(side="left", padx=(8, 0))
        self.output.trace_add("write", lambda *a: self.update_output_hint())
        self.update_output_hint()
        return page

    def update_output_hint(self) -> None:
        self.output_hint.configure(text=f"Lưu vào: {self.output.get()}  (đổi trong Cài đặt)")

    def start_from_text(self) -> None:
        self.start(self.links.get("1.0", "end"))

    def import_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV / TXT", "*.csv *.txt *.tsv"), ("Tất cả", "*.*")])
        if not path:
            return
        if Path(path).stat().st_size > 1_000_000:
            return messagebox.showerror("Nhập từ file", "File tối đa 1 MB.")
        raw = Path(path).read_bytes()
        for encoding in ("utf-8-sig", "utf-16", "cp1258", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        self.start(text)

    def start(self, text: str) -> None:
        try:
            items = ytcore.parse_import(text)
        except ValueError as e:
            return messagebox.showerror("Link chưa đúng", str(e))
        self.save_settings()
        for item in items:
            self.add_job(item.url, item.url if item.kind == "video" else f"Kênh: {item.url}", None,
                         "Chờ liệt kê video…" if item.kind == "channel" else "Chờ tải", kind=item.kind)
        self.links.delete("1.0", "end")
        self.ensure_worker()

    def add_job(self, url, title, channel, status, kind="video") -> dict:
        if kind == "video" and any(j["url"] == url and j["status"] not in ("Lỗi", "Đã dừng") for j in self.jobs if j["kind"] == "video"):
            return {}
        iid = self.queue_view.insert("", "end", values=(title, channel or "", status, "", ""))
        job = {"iid": iid, "url": url, "kind": kind, "status": "Chờ", "title": title}
        self.jobs.append(job)
        self.update_overall()
        return job

    def retry_failed(self) -> None:
        for job in self.jobs:
            if job["status"] in ("Lỗi", "Đã dừng"):
                job["status"] = "Chờ"
                self.queue_view.item(job["iid"], tags=(), values=(job["title"], self.queue_view.set(job["iid"], "channel"), "Chờ tải", "", ""))
        self.ensure_worker()

    def clear_done(self) -> None:
        for job in [j for j in self.jobs if j["status"] in ("Xong", "Đã có")]:
            self.queue_view.delete(job["iid"])
            self.jobs.remove(job)
        self.update_overall()

    def request_stop(self) -> None:
        self.stop.set()
        self.status.set("Đang dừng sau thao tác hiện tại…")

    def ensure_worker(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.stop.clear()
        # Biến Tk chỉ được đọc trên luồng giao diện; chụp lại trước khi giao cho luồng tải.
        self.run_output = Path(self.output.get())
        self.run_height = QUALITIES[self.quality.get()]
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.worker = threading.Thread(target=self.work, daemon=True)
        self.worker.start()

    def next_job(self) -> dict | None:
        pending = [j for j in self.jobs if j["status"] == "Chờ"]
        # Liệt kê kênh trước để biết tổng số video.
        return next((j for j in pending if j["kind"] == "channel"), pending[0] if pending else None)

    def work(self) -> None:
        """Chạy trên luồng phụ; chỉ gửi sự kiện về giao diện qua self.events."""
        try:
            if self.tools is None:
                self.tools = ytcore.ensure_tools(lambda m, f=None: self.events.put(("status", m + (f" {f:.0%}" if f else ""))))
            while not self.stop.is_set():
                job = self.next_job()
                if not job:
                    break
                job["status"] = "Đang chạy"
                if job["kind"] == "channel":
                    self.run_channel(job)
                else:
                    self.run_video(job)
        except Exception as e:  # lỗi cài công cụ / mạng
            self.events.put(("status", f"Lỗi: {e}"))
        finally:
            self.events.put(("idle", None))

    def run_channel(self, job: dict) -> None:
        self.events.put(("row", job, {"status": "Đang liệt kê video…"}))
        found = []
        try:
            def add(video):
                found.append(video)
                if len(found) % 25 == 0:
                    self.events.put(("row", job, {"status": f"Đã thấy {len(found)} video…"}))
            ytcore.expand(ytcore.YoutubeInput(job["url"], "channel"), self.tools, add, self.stop.is_set)
        except ytcore.Cancelled:
            job["status"] = "Đã dừng"
            self.events.put(("row", job, {"status": "Đã dừng"}))
            return
        except Exception as e:
            job["status"] = "Lỗi"
            self.events.put(("row", job, {"status": f"Lỗi: {short(e)}", "tag": "err"}))
            return
        job["status"] = "Xong"
        self.events.put(("row", job, {"status": f"Đã thêm {len(found)} video", "tag": "ok"}))
        self.events.put(("videos", found))

    def run_video(self, job: dict) -> None:
        self.events.put(("row", job, {"status": "Đang tải…"}))

        def progress(fraction, speed):
            text = f"{fraction:.0%}" if fraction is not None else ""
            self.events.put(("row", job, {"progress": text, "status": "Đang tải" + (f" · {ytcore.human_size(speed)}/s" if speed else "…")}))

        try:
            result = ytcore.download(job["url"], self.run_output, self.run_height, self.tools, progress, self.stop.is_set)
        except ytcore.Cancelled:
            job["status"] = "Đã dừng"
            self.events.put(("row", job, {"status": "Đã dừng", "progress": ""}))
            return
        except Exception as e:
            job["status"] = "Lỗi"
            self.events.put(("row", job, {"status": f"Lỗi: {short(e)}", "tag": "err", "progress": ""}))
            return
        if result.get("skipped"):
            job["status"] = "Đã có"
            self.events.put(("row", job, {"status": "Đã có trong Kho video", "progress": "", "tag": "ok"}))
        else:
            job["status"] = "Xong"
            job["title"] = result["title"] or job["title"]
            self.events.put(("row", job, {"title": job["title"], "channel": result.get("channel") or "", "status": "Xong",
                                          "progress": "100%", "size": ytcore.human_size(result.get("size")), "tag": "ok"}))

    def pump(self) -> None:
        try:
            while True:
                kind, *data = self.events.get_nowait()
                if kind == "status":
                    self.status.set(data[0])
                elif kind == "row":
                    job, change = data
                    if self.queue_view.exists(job["iid"]):
                        for key in ("title", "channel", "status", "progress", "size"):
                            if key in change:
                                self.queue_view.set(job["iid"], key, change[key])
                        if "tag" in change:
                            self.queue_view.item(job["iid"], tags=(change["tag"],))
                    self.update_overall()
                elif kind == "videos":
                    for video in data[0]:
                        self.add_job(video["url"], video["title"], video["channel"], "Chờ tải")
                elif kind == "auto":
                    self.auto.on_event(*data)
                elif kind == "idle":
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    if any(j["status"] == "Chờ" for j in self.jobs) and not self.stop.is_set():
                        self.ensure_worker()
                    else:
                        self.update_overall(final=True)
                        self.refresh_library()
        except queue.Empty:
            pass
        self.after(150, self.pump)

    def update_overall(self, final: bool = False) -> None:
        videos = [j for j in self.jobs if j["kind"] == "video"]
        done = sum(j["status"] in ("Xong", "Đã có") for j in videos)
        failed = sum(j["status"] == "Lỗi" for j in videos)
        self.overall.configure(maximum=max(1, len(videos)), value=done + failed)
        if videos:
            text = f"Tải thủ công: {done}/{len(videos)} video xong" + (f" · {failed} lỗi" if failed else "")
            self.status.set(text + (" · Hoàn tất." if final else ""))

    # ---------- Kho video ----------
    def build_library(self, parent) -> ttk.Frame:
        page = T.Page(parent, "Kho video",
                      "Video đã tải về máy, chờ đăng lên Facebook. Tới mỗi khung giờ, tool lấy video cũ nhất chưa "
                      "đăng (dòng “Đăng tiếp theo”). Không muốn đăng video nào thì xóa video đó khỏi kho.")
        box = T.card(page, expand=True)
        bar = T.row(box, pady=(0, 10))
        T.label(bar, "Tìm").pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self.render_library())
        ttk.Entry(bar, textvariable=self.search, width=26).pack(side="left", padx=(6, 14))
        self.channel_filter = tk.StringVar(value="Tất cả kênh")
        self.channel_box = ttk.Combobox(bar, textvariable=self.channel_filter, state="readonly", width=26)
        self.channel_box.pack(side="left")
        self.channel_box.bind("<<ComboboxSelected>>", lambda e: self.render_library())
        self.post_filter = tk.StringVar(value=POST_FILTERS[0])
        box_state = ttk.Combobox(bar, textvariable=self.post_filter, values=POST_FILTERS, state="readonly", width=18)
        box_state.pack(side="left", padx=8)
        box_state.bind("<<ComboboxSelected>>", lambda e: self.render_library())
        ttk.Button(bar, text="Làm mới", command=self.refresh_library).pack(side="right")

        self.library_view = T.table(box, [
            ("title", "Video", 300, "w", True), ("channel", "Kênh", 140, "w", False),
            ("duration", "Thời lượng", 80, "e", False), ("size", "Dung lượng", 80, "e", False),
            ("post", "Đăng Facebook", 150, "w", False)])
        self.library_view.bind("<Double-1>", lambda e: self.on_selected(lambda v: open_path(v["file"])))
        bar = T.row(box)
        ttk.Button(bar, text="▶  Xem video", command=lambda: self.on_selected(lambda v: open_path(v["file"]))).pack(side="left")
        ttk.Button(bar, text="Mở thư mục", command=lambda: self.on_selected(self.reveal)).pack(side="left", padx=8)
        ttk.Button(bar, text="Lưu thumbnail…", command=lambda: self.on_selected(self.save_thumbnail)).pack(side="left")
        ttk.Button(bar, text="Mở trên YouTube", command=lambda: self.on_selected(lambda v: v["url"] and open_url(v["url"]))).pack(side="left", padx=8)
        ttk.Button(bar, text="Xóa khỏi kho", command=self.delete_selected).pack(side="left")
        self.library_summary = T.label(bar, kind="muted")
        self.library_summary.pack(side="right")
        return page

    def refresh_library(self) -> None:
        self.library = ytcore.scan_library(Path(self.output.get()))
        counts: dict[str, int] = {}
        for v in self.library:
            counts[v["channel"]] = counts.get(v["channel"], 0) + 1
        self.channel_names = {f"{c} ({n})": c for c, n in sorted(counts.items())}
        self.channel_box.configure(values=["Tất cả kênh"] + list(self.channel_names))
        if self.channel_filter.get() not in self.channel_box.cget("values"):
            self.channel_filter.set("Tất cả kênh")
        self.render_library()
        if hasattr(self, "auto"):
            self.auto.render()

    def render_library(self) -> None:
        channel = self.channel_names.get(self.channel_filter.get())
        term = self.search.get().strip().lower()
        wanted = self.post_filter.get()
        selected = set(self.library_view.selection())
        self.library_view.delete(*self.library_view.get_children())
        self.shown = {}
        total = 0
        for v in self.library:
            text, tag = self.auto.video_status(v) if hasattr(self, "auto") else ("", "")
            group = "Đã đăng" if tag == "ok" else "Cần kiểm tra" if tag == "warn" else "Chờ đăng"
            if (channel and v["channel"] != channel) or (term and term not in v["title"].lower()) \
                    or (wanted != POST_FILTERS[0] and wanted != group):
                continue
            iid = v["file"]
            self.library_view.insert("", "end", iid=iid, tags=(tag,), values=(
                v["title"], v["channel"], ytcore.human_duration(v["duration"]), ytcore.human_size(v["size"]), text))
            self.shown[iid] = v
            total += v["size"]
        keep = [i for i in selected if i in self.shown]
        if keep:
            self.library_view.selection_set(keep)
        self.library_summary.configure(text=f"{len(self.shown)} video · {ytcore.human_size(total) or '0 B'}")

    def selected_videos(self) -> list[dict]:
        return [self.shown[i] for i in self.library_view.selection() if i in self.shown]

    def on_selected(self, action) -> None:
        videos = self.selected_videos()
        if not videos:
            return messagebox.showinfo("Kho video", "Chọn một video trong danh sách trước.")
        action(videos[0])

    def reveal(self, video: dict) -> None:
        if os.name == "nt":
            subprocess.run(["explorer", "/select,", video["file"]], check=False)
        else:
            open_path(str(Path(video["file"]).parent))

    def save_thumbnail(self, video: dict) -> None:
        if not video.get("thumbnail"):
            return messagebox.showinfo("Thumbnail", "Video này chưa có thumbnail.")
        target = filedialog.asksaveasfilename(defaultextension=".jpg", initialfile=Path(video["thumbnail"]).name, filetypes=[("JPEG", "*.jpg")])
        if target:
            shutil.copyfile(video["thumbnail"], target)

    def delete_selected(self) -> None:
        videos = self.selected_videos()
        if not videos:
            return messagebox.showinfo("Kho video", "Chọn video cần xóa.")
        if not messagebox.askyesno("Xóa khỏi kho", f"Xóa {len(videos)} video khỏi máy (gồm thumbnail)? Video đã xóa sẽ không được đăng và không khôi phục được."):
            return
        for video in videos:
            ytcore.delete_video(video, Path(self.output.get()))
        self.refresh_library()

    # ---------- Cài đặt ----------
    def build_settings(self, parent) -> ttk.Frame:
        page = T.Page(parent, "Cài đặt")
        box = T.card(page, "Thư mục Kho video", "Nơi lưu video tải về. Tool đăng video lấy từ thư mục này.")
        bar = T.row(box)
        ttk.Entry(bar, textvariable=self.output).pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text="Chọn…", command=self.choose_output).pack(side="left", padx=8)
        ttk.Button(bar, text="Mở thư mục", command=self.open_output).pack(side="left")
        box = T.card(page, "Chất lượng video", "Tải ở độ phân giải cao nhất có, không vượt quá mức này.")
        ttk.Combobox(box, textvariable=self.quality, values=list(QUALITIES), width=10, state="readonly").pack(anchor="w")
        self.auto.build_settings(page)
        return page

    def update_snapshot(self) -> None:
        try:
            self.snapshot = (Path(self.output.get()), QUALITIES[self.quality.get()])
        except KeyError:
            pass

    def choose_output(self) -> None:
        path = filedialog.askdirectory(initialdir=self.output.get())
        if path:
            self.output.set(path)
            self.save_settings()
            self.refresh_library()

    def open_output(self) -> None:
        Path(self.output.get()).mkdir(parents=True, exist_ok=True)
        open_path(self.output.get())

    def save_settings(self) -> None:
        try:
            SETTINGS.write_text(json.dumps({"output": self.output.get(), "quality": self.quality.get()}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def on_close(self) -> None:
        if self.worker and self.worker.is_alive() and not messagebox.askyesno("Thoát", "Đang tải. Dừng và thoát?"):
            return
        if self.auto.engine.busy and not messagebox.askyesno("Thoát", "Bot đang chạy (tải hoặc đăng Facebook). Vẫn thoát?"):
            return
        self.stop.set()
        self.auto.shutdown()
        self.save_settings()
        self.destroy()


def short(error: Exception) -> str:
    text = str(error).strip().splitlines()[-1] if str(error).strip() else type(error).__name__
    return text[:160]


def open_url(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


if __name__ == "__main__":
    App().mainloop()
