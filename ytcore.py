"""Logic không phụ thuộc giao diện: đọc link, cài công cụ, tải video, quét thư viện."""
from __future__ import annotations

import csv
import io
import json
import os
import platform
import re
import shutil
import stat
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
URL_HEADERS = {"url", "link", "youtube_url"}
ARCHIVE = ".da-tai.txt"
EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}


def safe_stem(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .") or "Video"
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", name, re.I):
        name += "_"
    return name


@dataclass(frozen=True)
class YoutubeInput:
    url: str
    kind: str  # "video" | "channel"
    youtube_id: str | None = None


def youtube_input(value: str) -> YoutubeInput:
    """Giống bản web: nhận link video (watch, youtu.be, shorts, live, embed) hoặc link kênh."""
    try:
        url = urlparse(value.strip())
    except ValueError:
        raise ValueError("Link YouTube không hợp lệ.")
    if url.scheme != "https" or url.username or url.password or url.port:
        raise ValueError("Chỉ nhận link YouTube HTTPS.")
    host = (url.hostname or "").lower()
    if host not in HOSTS:
        raise ValueError("Chỉ nhận link YouTube.")
    path = url.path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if host == "youtu.be":
        candidate = parts[0] if parts else None
    elif path == "/watch":
        candidate = (parse_qs(url.query).get("v") or [None])[0]
    elif parts and parts[0] in ("shorts", "live", "embed"):
        candidate = parts[1] if len(parts) > 1 else None
    else:
        candidate = None
    if candidate:
        if not VIDEO_ID.match(candidate):
            raise ValueError("ID video YouTube không hợp lệ.")
        return YoutubeInput(f"https://www.youtube.com/watch?v={candidate}", "video", candidate)
    if host == "youtu.be":
        raise ValueError("Link video không hợp lệ.")
    root = re.sub(r"/(videos|shorts|streams|featured)$", "", path)
    if not (
        re.match(r"^/@[^/\s]+$", root)
        or re.match(r"^/channel/UC[A-Za-z0-9_-]{22}$", root)
        or re.match(r"^/(c|user)/[^/\s]+$", root)
    ):
        raise ValueError("Dán link video hoặc kênh YouTube.")
    return YoutubeInput(f"https://www.youtube.com{root}", "channel")


def parse_import(text: str) -> list[YoutubeInput]:
    """Danh sách link dán tay hoặc file CSV/TXT/TSV; có cột url/link/youtube_url thì đọc cột đó."""
    if len(text) > 1_000_000:
        raise ValueError("File tối đa 1 MB.")
    text = text.lstrip("﻿").strip()
    if not text:
        raise ValueError("Nhập ít nhất một link.")
    first = text.splitlines()[0]
    delimiter = "\t" if "\t" in first else ";" if ";" in first else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)]
    index, start = 0, 0
    header = [c.strip().lower() for c in rows[0]] if rows else []
    if any(h in URL_HEADERS for h in header):
        index = next(i for i, h in enumerate(header) if h in URL_HEADERS)
        start = 1
    if len(rows) - start > 2000:
        raise ValueError("Mỗi lần nhập tối đa 2.000 link.")
    result: dict[str, YoutubeInput] = {}
    for i in range(start, len(rows)):
        cell = rows[i][index].strip() if index < len(rows[i]) else ""
        try:
            item = youtube_input(cell)
        except ValueError as e:
            raise ValueError(f"Dòng {i + 1}: {e}")
        result[item.url] = item
    if not result:
        raise ValueError("File chưa có link video/kênh.")
    return list(result.values())


# ---------- Công cụ đi kèm (ffmpeg, deno) ----------

def app_dir() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    return base


def tools_dir() -> Path:
    d = app_dir() / "tools"
    d.mkdir(exist_ok=True)
    return d


def _exe(name: str) -> str:
    return name + ".exe" if os.name == "nt" else name


def _download(url: str, target: Path, report) -> None:
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                report(done / total)
    tmp.replace(target)


def _extract(archive: Path, names: list[str], into: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        for member in z.namelist():
            if Path(member).name in names:
                out = into / Path(member).name
                with z.open(member) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                out.chmod(out.stat().st_mode | stat.S_IEXEC)


def _deno_asset() -> str:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if os.name == "nt":
        return "deno-x86_64-pc-windows-msvc.zip"
    if sys.platform == "darwin":
        return f"deno-{'aarch64' if arm else 'x86_64'}-apple-darwin.zip"
    return f"deno-{'aarch64' if arm else 'x86_64'}-unknown-linux-gnu.zip"


def ensure_tools(report=lambda message, fraction=None: None) -> dict[str, str]:
    """Tải ffmpeg (ghép hình + tiếng) và deno (yt-dlp cần để giải mã link YouTube) vào thư mục tools."""
    d = tools_dir()
    found = {}
    ffmpeg = d / _exe("ffmpeg")
    if not ffmpeg.exists():
        system = shutil.which("ffmpeg")
        if system and os.name != "nt":
            found["ffmpeg"] = system
        else:
            archive = d / "ffmpeg.zip"
            _download(
                "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                archive,
                lambda f: report("Đang tải ffmpeg (lần đầu, khoảng 200 MB)…", f),
            )
            _extract(archive, ["ffmpeg.exe", "ffprobe.exe"], d)
            archive.unlink()
    found.setdefault("ffmpeg", str(ffmpeg))
    deno = d / _exe("deno")
    if not deno.exists():
        archive = d / "deno.zip"
        _download(
            f"https://github.com/denoland/deno/releases/latest/download/{_deno_asset()}",
            archive,
            lambda f: report("Đang tải deno (lần đầu, khoảng 45 MB)…", f),
        )
        _extract(archive, [_exe("deno")], d)
        archive.unlink()
    found["deno"] = str(deno)
    return found


# ---------- Tải ----------

class Cancelled(Exception):
    pass


class YoutubeAuthRequired(RuntimeError):
    pass


class YoutubeRateLimited(RuntimeError):
    pass


def download_error(error: Exception) -> RuntimeError:
    message = str(error)
    low = message.lower()
    if any(s in low for s in ("sign in to confirm", "sign in to verify", "cookies are no longer valid",
                              "login required", "cookies have expired", "failed to decrypt", "cookie database", "dpapi")):
        return RuntimeError("YouTube chặn video này (riêng tư, giới hạn tuổi, hoặc theo khu vực). Bỏ qua, thử video khác.")
    if "429" in low or "too many requests" in low or "rate limit" in low:
        return YoutubeRateLimited("YouTube đang giới hạn lượt tải. Đã tạm dừng hàng đợi; đợi một lúc rồi bấm Tiếp tục.")
    message = re.sub(r"https?://\S+", "[link]", message).replace("ERROR: ", "")
    return RuntimeError(message[-300:] or "Không tải được video.")


def base_options(tools: dict[str, str]) -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 3,
        "extractor_retries": 2,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 1,
        "sleep_interval_requests": 1,
        "sleep_interval": 2,
        "ffmpeg_location": str(Path(tools["ffmpeg"]).parent) if os.name == "nt" else tools["ffmpeg"],
        "js_runtimes": {"deno": {"path": tools["deno"]}},
    }


def expand(item: YoutubeInput, tools: dict[str, str], on_video, should_stop) -> int:
    from yt_dlp.utils import DownloadError
    try:
        return _expand(item, tools, on_video, should_stop)
    except DownloadError as e:
        if isinstance(e.exc_info[1] if e.exc_info else None, Cancelled):
            raise Cancelled() from None
        raise download_error(e) from None


def _expand(item: YoutubeInput, tools: dict[str, str], on_video, should_stop) -> int:
    """Liệt kê mọi video công khai của kênh (gồm Shorts), bỏ qua live/sắp phát. Trả về số video."""
    from yt_dlp import YoutubeDL

    if item.kind == "video":
        on_video({"id": item.youtube_id, "title": item.url, "channel": None, "url": item.url})
        return 1
    seen: set[str] = set()
    with YoutubeDL({**base_options(tools), "extract_flat": "in_playlist", "lazy_playlist": True}) as ydl:
        def walk(url: str, depth: int = 0) -> None:
            info = ydl.extract_info(url, download=False)
            for entry in info.get("entries") or []:
                if should_stop():
                    raise Cancelled()
                if not entry:
                    continue
                if entry.get("ie_key") == "YoutubeTab" or entry.get("_type") == "playlist":
                    if depth < 2 and entry.get("url"):
                        walk(entry["url"], depth + 1)
                    continue
                vid = entry.get("id")
                if not vid or not VIDEO_ID.match(vid) or vid in seen:
                    continue
                if entry.get("live_status") in ("is_live", "is_upcoming"):
                    continue
                if entry.get("availability") not in (None, "public", "unlisted"):
                    continue
                seen.add(vid)
                on_video({
                    "id": vid,
                    "title": entry.get("title") or vid,
                    "channel": entry.get("channel") or info.get("channel") or info.get("uploader"),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                })

        walk(item.url)
    return len(seen)


def download(url: str, output: Path, height: int, tools: dict[str, str], on_progress, should_stop) -> dict:
    """Tải một video MP4 (≤ height p) kèm thumbnail JPG và info.json vào output/<Kênh>/."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    output.mkdir(parents=True, exist_ok=True)
    result: dict = {}

    def hook(d):
        if should_stop():
            raise Cancelled()
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            on_progress(d.get("downloaded_bytes", 0) / total if total else None, d.get("speed"))
        elif d["status"] == "finished":
            on_progress(1.0, None)

    def post(d):
        if d["status"] == "finished" and d.get("postprocessor") == "MoveFiles":
            result["file"] = d["info_dict"].get("filepath")

    options = {
        **base_options(tools),
        "noplaylist": True,
        "paths": {"home": str(output)},
        "outtmpl": {"default": "%(channel,uploader|Không rõ kênh)s/%(title).120B [%(id)s].%(ext)s"},
        "windowsfilenames": True,
        "format_sort": [f"res:{height}", "fps:30", "br"],
        "format": f"bv*[height<={height}]+ba/b[height<={height}]",
        "merge_output_format": "mp4",
        "max_filesize": 2 * 1024**3,
        "writethumbnail": True,
        "writeinfojson": True,
        "download_archive": str(output / ARCHIVE),
        "postprocessors": [
            {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
        ],
        "progress_hooks": [hook],
        "postprocessor_hooks": [post],
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadError as e:
        if isinstance(e.exc_info[1] if e.exc_info else None, Cancelled):
            raise Cancelled()
        raise download_error(e) from None
    if info is None:
        return {"skipped": True}
    file = result.get("file") or info.get("filepath") or (info.get("requested_downloads") or [{}])[0].get("filepath")
    return {
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "file": file,
        "size": Path(file).stat().st_size if file and Path(file).exists() else None,
        "skipped": not file,
    }


# ---------- Thư viện ----------

def scan_library(output: Path) -> list[dict]:
    """Đọc mọi *.info.json trong thư mục tải; chỉ liệt kê video còn file MP4."""
    videos = []
    if not output.exists():
        return videos
    for meta in output.rglob("*.info.json"):
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stem = meta.name[: -len(".info.json")]
        video = next((meta.with_name(stem + ext) for ext in [".mp4", *sorted(EXTS - {".mp4"})]
                      if meta.with_name(stem + ext).is_file()), None)
        if video is None:
            continue
        thumb = meta.with_name(stem + ".jpg")
        videos.append({
            "id": info.get("id"),
            "title": info.get("title") or stem,
            "channel": info.get("channel") or info.get("uploader") or meta.parent.name,
            "duration": info.get("duration"),
            "width": info.get("width"),
            "height": info.get("height"),
            "size": video.stat().st_size,
            "upload_date": info.get("upload_date"),
            "url": info.get("webpage_url"),
            "file": str(video),
            "thumbnail": str(thumb) if thumb.exists() else None,
            "info": str(meta),
            "modified": video.stat().st_mtime,
        })
    videos.sort(key=lambda v: v["modified"], reverse=True)
    return videos


def delete_video(video: dict, output: Path) -> None:
    """Xóa MP4, thumbnail, info.json và gỡ ID khỏi danh sách đã tải để có thể tải lại."""
    for key in ("file", "thumbnail", "info"):
        if video.get(key):
            Path(video[key]).unlink(missing_ok=True)
    archive = output / ARCHIVE
    if video.get("id") and archive.exists():
        lines = archive.read_text(encoding="utf-8").splitlines()
        archive.write_text(
            "".join(l + "\n" for l in lines if l.strip() != f"youtube {video['id']}"), encoding="utf-8"
        )


def human_size(n: float | None) -> str:
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def human_duration(sec) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, m, s = sec // 3600, sec // 60 % 60, sec % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"
