"""YouTube Downloader — tải video YouTube về máy và render lại khung hình. Không liên quan Facebook."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

import crawl
import render as render_mod
import ytcore
import webserver

ROOT = ytcore.app_dir()
SETTINGS = ROOT / "settings.json"
QUALITIES = {"1080p": 1080, "720p": 720, "480p": 480, "360p": 360}
MAX_HISTORY = 500


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Api:
    def __init__(self):
        s = load_settings()
        self.output = s.get("output") or str(Path.home() / "Videos" / "YouTube")
        self.quality = s.get("quality") if s.get("quality") in QUALITIES else "1080p"
        self.render_ratio = s.get("render_ratio") or "9:16"
        self.render_fit = s.get("render_fit") if s.get("render_fit") in ("blur", "crop", "pad") else "blur"
        self.frame_dir = s.get("frame_dir") or ""
        self.downloads = s.get("downloads") or []
        self.logs: deque[str] = deque(maxlen=300)
        self.jobs: list[dict] = []
        self.tools = None
        self.dialog = None
        self.dl_lock = threading.Lock()
        self.dl_stop = threading.Event()
        self.dl_thread: threading.Thread | None = None
        self.paused = False
        self.render_job = {"status": "idle", "title": "", "output": "", "error": ""}

    # ---------- state ----------
    def _settings(self):
        return (Path(self.output), QUALITIES[self.quality])

    def save(self):
        try:
            SETTINGS.write_text(json.dumps({
                "output": self.output, "quality": self.quality, "render_ratio": self.render_ratio,
                "render_fit": self.render_fit, "frame_dir": self.frame_dir,
                "downloads": self.downloads[:MAX_HISTORY]}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def log(self, m):
        self.logs.append(f"{datetime.now():%H:%M} {m}")

    def add_history(self, rec):
        self.downloads = ([rec] + self.downloads)[:MAX_HISTORY]
        self.save()

    def render_settings(self):
        return {"render_enabled": True, "render_ratio": self.render_ratio,
                "render_fit": self.render_fit, "frame_dir": self.frame_dir}

    def snapshot(self):
        output = Path(self.output)
        library = crawl.library(output)
        dl_map = {x["file"]: x.get("at", "") for x in self.downloads if x.get("file")}
        videos = []
        for v in library:
            rpath = Path(v["file"]).parent / render_mod.RENDER_SUBDIR / (Path(v["file"]).stem + ".mp4")
            videos.append({"title": v["title"], "channel": v["channel"], "file": v["file"], "url": v.get("url"),
                           "duration": ytcore.human_duration(v["duration"]), "size": ytcore.human_size(v["size"]),
                           "at": (dl_map.get(v["file"], "")).replace("T", " "),
                           "rendered": str(rpath) if rpath.is_file() else ""})
        return {
            "output": self.output, "quality": self.quality,
            "render": {"ratio": self.render_ratio, "fit": self.render_fit, "frame_dir": self.frame_dir,
                       "found": str(render_mod.frame_dir(self.frame_dir) or "")},
            "jobs": self.jobs, "paused": self.paused,
            "library": videos,
            "failed": [x for x in self.downloads if str(x.get("status", "")).startswith("Lỗi")][:50],
            "render_job": self.render_job,
            "log": list(self.logs)[-150:],
        }

    # ---------- actions ----------
    def action(self, req):
        fn = getattr(self, "do_" + (req.get("action") or ""), None)
        if not fn:
            raise ValueError("Thao tác không hợp lệ.")
        return fn(req) or {"ok": True}

    def do_set_output(self, req):
        if self.dialog:
            picked = self.dialog("folder")
            if picked:
                self.output = picked
                self.save()
        return {"ok": True}

    def do_set_quality(self, req):
        if req.get("quality") in QUALITIES:
            self.quality = req["quality"]
            self.save()
        return {"ok": True}

    def do_open(self, req):
        p = req.get("path")
        if p and Path(p).exists():
            if os.name == "nt":
                os.startfile(p)  # noqa: S606
            else:
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", p], check=False)
        return {"ok": True}

    def do_open_folder(self, req):
        p = req.get("path") or self.output
        d = p if Path(p).is_dir() else str(Path(p).parent)
        Path(d).mkdir(parents=True, exist_ok=True)
        return self.do_open({"path": d})

    def do_save_render(self, req):
        self.render_ratio = req.get("ratio") or "9:16"
        self.render_fit = req.get("fit") if req.get("fit") in ("blur", "crop", "pad") else "blur"
        self.frame_dir = (req.get("frame_dir") or "").strip()
        self.save()
        return {"ok": True, "found": str(render_mod.frame_dir(self.frame_dir) or "")}

    def do_pick_frame_dir(self, req):
        if self.dialog:
            picked = self.dialog("folder")
            if picked:
                self.frame_dir = picked
                self.save()
        return {"ok": True}

    # download
    def do_start_download(self, req):
        items = ytcore.parse_import(req.get("text") or "")
        limit = None
        raw = str(req.get("limit") or "").strip()
        if raw:
            if not raw.isdigit() or int(raw) < 1:
                raise ValueError("Giới hạn phải là số nguyên dương (để trống = tải tất cả).")
            limit = int(raw)
        with self.dl_lock:
            for it in items:
                if any(j["url"] == it.url and j["status"] not in ("Xong", "Đã có") for j in self.jobs):
                    continue
                self.jobs.append({"id": uuid.uuid4().hex, "url": it.url, "kind": it.kind,
                                  "title": it.url if it.kind == "video" else f"Kênh: {it.url}",
                                  "channel": "", "status": "Chờ", "progress": "",
                                  **({"limit": limit} if it.kind == "channel" and limit else {})})
        self.paused = False
        self._ensure_worker()
        return {"ok": True}

    def do_pause(self, req):
        self.paused = True
        self.dl_stop.set()
        return {"ok": True}

    def do_retry(self, req):
        with self.dl_lock:
            for j in self.jobs:
                if j["status"] == "Lỗi" and (not req.get("id") or req["id"] == j["id"]):
                    j.update(status="Chờ", progress="")
        self.paused = False
        self._ensure_worker()
        return {"ok": True}

    def do_clear_done(self, req):
        with self.dl_lock:
            self.jobs = [j for j in self.jobs if j["status"] not in ("Xong", "Đã có")]
        return {"ok": True}

    def _ensure_worker(self):
        if self.dl_thread and self.dl_thread.is_alive():
            return
        self.dl_stop.clear()
        self.dl_thread = threading.Thread(target=self._worker, daemon=True)
        self.dl_thread.start()

    def _worker(self):
        try:
            if self.tools is None:
                self.log("Chuẩn bị công cụ tải…")
                self.tools = crawl.ensure_tools(lambda m, f=None: self.log(m) if not f else None)
            output, height = self._settings()
            while not self.dl_stop.is_set():
                with self.dl_lock:
                    job = next((j for j in self.jobs if j["status"] == "Chờ" and j["kind"] == "channel"), None) \
                        or next((j for j in self.jobs if j["status"] == "Chờ"), None)
                if not job:
                    break
                job["status"] = "Đang chạy"
                (self._dl_channel if job["kind"] == "channel" else self._dl_video)(job, output, height)
        except Exception as e:
            self.log(f"Lỗi tải: {e}")

    def _dl_channel(self, job, output, height):
        count = 0

        def on_video(v):
            nonlocal count
            count += 1
            with self.dl_lock:
                if not any(j["url"] == v["url"] for j in self.jobs):
                    self.jobs.append({"id": uuid.uuid4().hex, "url": v["url"], "kind": "video",
                                      "title": v["title"], "channel": v["channel"], "status": "Chờ", "progress": ""})
        try:
            crawl.list_videos(crawl.resolve(job["url"]), self.tools, on_video, self.dl_stop.is_set, job.get("limit"))
        except ytcore.Cancelled:
            job.update(status="Chờ", progress="")
            return
        except Exception as e:
            job.update(status="Lỗi", progress=str(e)[:200])
            return
        job.update(status="Xong", progress=f"{count} video")

    def _dl_video(self, job, output, height):
        def progress(fraction, speed):
            job["progress"] = f"{fraction:.0%}" if fraction is not None else ""
        at = datetime.now().isoformat(timespec="minutes")
        try:
            result = crawl.download(job["url"], output, height, self.tools, progress, self.dl_stop.is_set)
        except ytcore.Cancelled:
            job.update(status="Chờ", progress="")
            return
        except Exception as e:
            job.update(status="Lỗi", progress=str(e)[:200])
            self.add_history({"at": at, "title": job["title"], "channel": job.get("channel"),
                              "url": job["url"], "file": None, "status": "Lỗi: " + str(e)[:120]})
            return
        if result.get("skipped"):
            job.update(status="Đã có", progress="")
        else:
            job.update(status="Xong", progress="100%", title=result.get("title") or job["title"],
                       channel=result.get("channel") or "")
        self.add_history({"at": at, "title": result.get("title") or job["title"], "channel": result.get("channel") or "",
                          "url": job["url"], "file": result.get("file"),
                          "status": "Đã có" if result.get("skipped") else "Đã tải"})

    # library
    def do_delete_video(self, req):
        for v in crawl.library(Path(self.output)):
            if v["file"] == req.get("file"):
                ytcore.delete_video(v, Path(self.output))
                break
        return {"ok": True}

    def do_import_videos(self, req):
        if not self.dialog:
            raise ValueError("Không mở được hộp thoại chọn file.")
        files = self.dialog("files")
        if not files:
            return {"ok": True, "added": 0}
        import shutil
        folder = Path(self.output) / "Video tải lên"
        folder.mkdir(parents=True, exist_ok=True)
        added = 0
        for raw in files:
            src = Path(raw)
            if src.suffix.lower() not in ytcore.EXTS or not src.is_file():
                continue
            vid = "local-" + uuid.uuid4().hex[:11]
            stem = ytcore.safe_stem(src.stem)[:120] + f" [{vid}]"
            dest = folder / (stem + ".mp4")
            shutil.copyfile(src, dest)
            dest.with_name(stem + ".info.json").write_text(json.dumps(
                {"id": vid, "title": src.stem, "channel": "Video tải lên", "webpage_url": None,
                 "duration": None, "width": None, "height": None}, ensure_ascii=False), encoding="utf-8")
            added += 1
        self.log(f"Đã thêm {added} video từ máy.")
        return {"ok": True, "added": added}

    # render
    def do_render_video(self, req):
        if self.render_job["status"] == "running":
            raise ValueError("Đang render video khác, đợi xong đã.")
        file = req.get("file")
        if not file or not Path(file).exists():
            raise ValueError("Chọn một video trước.")
        if not render_mod.frame_dir(self.frame_dir):
            raise ValueError("Chưa tìm thấy Frame Preview. Vào Cài đặt chọn thư mục chứa render_cli.py.")
        settings = {"render_enabled": True, "render_ratio": req.get("ratio") or self.render_ratio,
                    "render_fit": req.get("fit") if req.get("fit") in ("blur", "crop", "pad") else self.render_fit,
                    "frame_dir": self.frame_dir}
        self.render_job = {"status": "running", "title": Path(file).name, "output": "", "error": "",
                           "ratio": settings["render_ratio"], "fit": settings["render_fit"]}

        def work():
            try:
                out = render_mod.render(file, settings, lambda: False, self.log)
                if out and out != file and Path(out).exists():
                    self.render_job.update(status="done", output=out)
                else:
                    self.render_job.update(status="error", error="Render không ra file (xem nhật ký).")
            except Exception as e:
                self.render_job.update(status="error", error=str(e)[:200])
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def shutdown(self):
        self.dl_stop.set()


def main():
    (ROOT / "logs").mkdir(exist_ok=True)
    webserver.run(Api(), "YouTube Downloader", width=1060, height=760)


if __name__ == "__main__":
    main()
