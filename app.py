"""YouTube Downloader cho Windows: tab Tải video (link video/kênh, import CSV/TXT) và tab Thư viện."""
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

import ytcore

SETTINGS = ytcore.app_dir() / "settings.json"
QUALITIES = {"1080p": 1080, "720p": 720, "480p": 480, "360p": 360}


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
        self.title("YouTube Downloader")
        self.geometry("1100x680")
        self.minsize(820, 520)
        settings = load_settings()
        self.output = tk.StringVar(value=settings.get("output") or str(Path.home() / "Videos" / "YouTube"))
        self.quality = tk.StringVar(value=settings.get("quality") or "1080p")
        self.events: queue.Queue = queue.Queue()
        self.jobs: list[dict] = []  # {iid, url, title, channel, status}
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        self.tools: dict | None = None
        self.library: list[dict] = []
        # Luồng nền đọc bản sao này thay vì biến Tk.
        self.snapshot = (Path(self.output.get()), QUALITIES[self.quality.get()])
        for var in (self.output, self.quality):
            var.trace_add("write", lambda *a: self.update_snapshot())

        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=24)

        top = ttk.Frame(self, padding=(12, 10, 12, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Lưu vào:").pack(side="left")
        ttk.Entry(top, textvariable=self.output).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Chọn…", command=self.choose_output).pack(side="left")
        ttk.Button(top, text="Mở thư mục", command=lambda: self.open_output()).pack(side="left", padx=(6, 0))
        ttk.Label(top, text="Chất lượng tối đa:").pack(side="left", padx=(16, 4))
        ttk.Combobox(top, textvariable=self.quality, values=list(QUALITIES), width=7, state="readonly").pack(side="left")

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=12, pady=10)
        tabs.add(self.build_download(tabs), text="  Tải video  ")
        tabs.add(self.build_library(tabs), text="  Thư viện  ")
        import ui_auto

        self.auto = ui_auto.AutoTab(tabs, self)
        tabs.add(self.auto, text="  Facebook & Tự động  ")
        tabs.bind("<<NotebookTabChanged>>", lambda e: tabs.index("current") == 1 and self.refresh_library())

        self.status = tk.StringVar(value="Sẵn sàng.")
        ttk.Label(self, textvariable=self.status, padding=(12, 0, 12, 8), foreground="#555").pack(fill="x")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.pump)

    # ---------- Tab Tải video ----------
    def build_download(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=10)
        ttk.Label(frame, text="Link video hoặc kênh YouTube (mỗi dòng một link). Link kênh sẽ tải tất cả video công khai.").pack(anchor="w")
        self.links = tk.Text(frame, height=5, wrap="none", undo=True, font=("Segoe UI", 10))
        self.links.pack(fill="x", pady=(4, 6))
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        self.start_button = ttk.Button(bar, text="⬇ Tải video", command=self.start_from_text)
        self.start_button.pack(side="left")
        ttk.Button(bar, text="Import CSV / TXT", command=self.import_file).pack(side="left", padx=6)
        self.stop_button = ttk.Button(bar, text="Dừng", command=self.request_stop, state="disabled")
        self.stop_button.pack(side="left")
        ttk.Button(bar, text="Thử lại video lỗi", command=self.retry_failed).pack(side="left", padx=6)
        ttk.Button(bar, text="Xóa danh sách đã xong", command=self.clear_done).pack(side="left")

        columns = ("title", "channel", "status", "progress", "size")
        self.queue_view = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        for key, text, width, anchor in [
            ("title", "Video", 460, "w"), ("channel", "Kênh", 180, "w"), ("status", "Trạng thái", 200, "w"),
            ("progress", "Tiến độ", 80, "e"), ("size", "Dung lượng", 90, "e"),
        ]:
            self.queue_view.heading(key, text=text)
            self.queue_view.column(key, width=width, anchor=anchor, stretch=key == "title")
        self.queue_view.tag_configure("error", foreground="#b00020")
        self.queue_view.tag_configure("done", foreground="#1b7f3b")
        self.add_scrolled(frame, self.queue_view)
        self.overall = ttk.Progressbar(frame, mode="determinate")
        self.overall.pack(fill="x", pady=(6, 0))
        return frame

    def add_scrolled(self, frame, tree) -> None:
        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True, pady=(8, 0))
        scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(in_=holder, side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def start_from_text(self) -> None:
        self.start(self.links.get("1.0", "end"))

    def import_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV / TXT", "*.csv *.txt *.tsv"), ("Tất cả", "*.*")])
        if not path:
            return
        if Path(path).stat().st_size > 1_000_000:
            return messagebox.showerror("Import", "File tối đa 1 MB.")
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
            self.events.put(("row", job, {"status": f"Lỗi: {short(e)}", "tag": "error"}))
            return
        job["status"] = "Xong"
        self.events.put(("row", job, {"status": f"Đã thêm {len(found)} video", "tag": "done"}))
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
            self.events.put(("row", job, {"status": f"Lỗi: {short(e)}", "tag": "error", "progress": ""}))
            return
        if result.get("skipped"):
            job["status"] = "Đã có"
            self.events.put(("row", job, {"status": "Đã có trong thư mục", "progress": "", "tag": "done"}))
        else:
            job["status"] = "Xong"
            job["title"] = result["title"] or job["title"]
            self.events.put(("row", job, {"title": job["title"], "channel": result.get("channel") or "", "status": "Xong",
                                          "progress": "100%", "size": ytcore.human_size(result.get("size")), "tag": "done"}))

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
        except queue.Empty:
            pass
        self.after(150, self.pump)

    def update_overall(self, final: bool = False) -> None:
        videos = [j for j in self.jobs if j["kind"] == "video"]
        done = sum(j["status"] in ("Xong", "Đã có") for j in videos)
        failed = sum(j["status"] == "Lỗi" for j in videos)
        self.overall.configure(maximum=max(1, len(videos)), value=done + failed)
        if videos:
            text = f"{done}/{len(videos)} video xong" + (f" · {failed} lỗi" if failed else "")
            self.status.set(text + (" · Hoàn tất." if final else ""))

    # ---------- Tab Thư viện ----------
    def build_library(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=10)
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        ttk.Label(bar, text="Kênh:").pack(side="left")
        self.channel_filter = tk.StringVar(value="Tất cả kênh")
        self.channel_box = ttk.Combobox(bar, textvariable=self.channel_filter, state="readonly", width=32)
        self.channel_box.pack(side="left", padx=(4, 12))
        self.channel_box.bind("<<ComboboxSelected>>", lambda e: self.render_library())
        ttk.Label(bar, text="Tìm:").pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self.render_library())
        ttk.Entry(bar, textvariable=self.search, width=30).pack(side="left", padx=4)
        ttk.Button(bar, text="Làm mới", command=self.refresh_library).pack(side="left", padx=6)
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="▶ Mở video", command=lambda: self.on_selected(lambda v: open_path(v["file"]))).pack(side="left")
        ttk.Button(actions, text="Mở thư mục", command=lambda: self.on_selected(self.reveal)).pack(side="left", padx=6)
        ttk.Button(actions, text="Lưu thumbnail…", command=lambda: self.on_selected(self.save_thumbnail)).pack(side="left")
        ttk.Button(actions, text="Mở trên YouTube", command=lambda: self.on_selected(lambda v: v["url"] and open_url(v["url"]))).pack(side="left", padx=6)
        ttk.Button(actions, text="Xóa video", command=self.delete_selected).pack(side="left")

        columns = ("title", "channel", "duration", "quality", "size")
        self.library_view = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        for key, text, width, anchor in [
            ("title", "Video", 520, "w"), ("channel", "Kênh", 200, "w"), ("duration", "Thời lượng", 90, "e"),
            ("quality", "Độ phân giải", 100, "e"), ("size", "Dung lượng", 90, "e"),
        ]:
            self.library_view.heading(key, text=text)
            self.library_view.column(key, width=width, anchor=anchor, stretch=key == "title")
        self.library_view.bind("<Double-1>", lambda e: self.on_selected(lambda v: open_path(v["file"])))
        self.add_scrolled(frame, self.library_view)
        self.library_summary = tk.StringVar()
        ttk.Label(frame, textvariable=self.library_summary, foreground="#555").pack(anchor="w", pady=(6, 0))
        return frame

    def refresh_library(self) -> None:
        self.library = ytcore.scan_library(Path(self.output.get()))
        counts: dict[str, int] = {}
        for v in self.library:
            counts[v["channel"]] = counts.get(v["channel"], 0) + 1
        self.channel_box.configure(values=["Tất cả kênh"] + [f"{c} ({n})" for c, n in sorted(counts.items())])
        if self.channel_filter.get() not in self.channel_box.cget("values"):
            self.channel_filter.set("Tất cả kênh")
        self.render_library()

    def visible_library(self) -> list[dict]:
        channel = self.channel_filter.get()
        term = self.search.get().strip().lower()
        return [
            v for v in self.library
            if (channel == "Tất cả kênh" or channel == f"{v['channel']} ({sum(x['channel'] == v['channel'] for x in self.library)})")
            and (not term or term in v["title"].lower())
        ]

    def render_library(self) -> None:
        self.library_view.delete(*self.library_view.get_children())
        shown = self.visible_library()
        for i, v in enumerate(shown):
            quality = f"{v['width']}×{v['height']}" if v.get("width") else ""
            self.library_view.insert("", "end", iid=str(i), values=(v["title"], v["channel"], ytcore.human_duration(v["duration"]), quality, ytcore.human_size(v["size"])))
        self.shown = shown
        total = sum(v["size"] for v in shown)
        self.library_summary.set(f"{len(shown)} video · {ytcore.human_size(total) or '0 B'}")

    def selected_videos(self) -> list[dict]:
        return [self.shown[int(i)] for i in self.library_view.selection()]

    def on_selected(self, action) -> None:
        videos = self.selected_videos()
        if not videos:
            return messagebox.showinfo("Thư viện", "Chọn một video trước.")
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
            return messagebox.showinfo("Thư viện", "Chọn video cần xóa.")
        if not messagebox.askyesno("Xóa video", f"Xóa {len(videos)} video khỏi máy (gồm thumbnail)? Không khôi phục được."):
            return
        for video in videos:
            ytcore.delete_video(video, Path(self.output.get()))
        self.refresh_library()

    def update_snapshot(self) -> None:
        try:
            self.snapshot = (Path(self.output.get()), QUALITIES[self.quality.get()])
        except KeyError:
            pass

    # ---------- Chung ----------
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
        if self.auto.engine.busy and not messagebox.askyesno("Thoát", "Đang chạy tác vụ tự động (cào hoặc đăng Facebook). Vẫn thoát?"):
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
