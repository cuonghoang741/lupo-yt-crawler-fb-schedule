"""Module 2 — Render.

Gọi tool Frame Preview có sẵn để reframe video đã tải (ví dụ 9:16 nền mờ) trước khi
đăng. Không viết lại code render; chỉ chạy `render_cli.py` của Frame Preview.

Mặc định tắt. Khi bật, pipeline thành: cào+tải → render → đăng. Khi tắt (hoặc không
tìm thấy Frame Preview), trả về chính file gốc để đăng.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import ytcore

# Thư mục con (cạnh video gốc) chứa bản đã render.
RENDER_SUBDIR = "_render"
# Tên folder Frame Preview hay gặp, dò cạnh tool và ở các thư mục cha.
FRAME_DIRNAMES = ("Frame_Preview1", "FramePreview", "Frame Preview", "lupo-new-frame-video-generate-")


def frame_dir(configured: str = "") -> Path | None:
    """Tìm thư mục Frame Preview: biến môi trường → cấu hình → cạnh tool/thư mục cha."""
    candidates: list[Path] = []
    if os.environ.get("LUPO_FRAME_DIR"):
        candidates.append(Path(os.environ["LUPO_FRAME_DIR"]))
    if configured:
        candidates.append(Path(configured))
    here = ytcore.app_dir()
    for base in (here, *here.parents[:4]):
        for name in FRAME_DIRNAMES:
            candidates.append(base / name)
    for path in candidates:
        try:
            if (path / "render_cli.py").is_file():
                return path.resolve()
        except OSError:
            continue
    return None


def available(settings: dict) -> bool:
    return bool(settings.get("render_enabled")) and frame_dir(settings.get("frame_dir", "")) is not None


def _python() -> list[str]:
    """Trình Python để chạy render_cli: ưu tiên python đang chạy; bản .exe đóng gói thì tìm py/python."""
    exe = Path(sys.executable).name.lower()
    if not getattr(sys, "frozen", False) and ("python" in exe):
        return [sys.executable]
    for candidate in (["py", "-3.13"], ["py", "-3"], ["python"], ["python3"]):
        try:
            subprocess.run(candidate + ["--version"], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    return [sys.executable]


def render(video_file: str, settings: dict, should_stop=lambda: False, log=lambda m: None) -> str:
    """Render một video qua Frame Preview. Trả về đường dẫn bản đã render, hoặc file gốc nếu tắt/không có Frame."""
    if not settings.get("render_enabled"):
        return video_file
    frame = frame_dir(settings.get("frame_dir", ""))
    if not frame:
        log("Bật render nhưng không tìm thấy Frame Preview (đặt biến LUPO_FRAME_DIR hoặc chọn thư mục trong Cài đặt). Đăng bản gốc.")
        return video_file

    source = Path(video_file)
    out_dir = source.parent / RENDER_SUBDIR
    out_dir.mkdir(exist_ok=True)
    expected = out_dir / (source.stem + ".mp4")
    if expected.is_file() and expected.stat().st_mtime >= source.stat().st_mtime:
        return str(expected)  # đã render rồi, dùng lại

    cmd = _python() + [
        str(frame / "render_cli.py"),
        "--input", str(source),
        "--output-dir", str(out_dir),
        "--ratio", settings.get("render_ratio", "9:16"),
        "--fit", settings.get("render_fit", "blur"),
        "--device", "auto",
        "--json",
    ]
    log(f"Render {source.name} → {settings.get('render_ratio', '9:16')} ({settings.get('render_fit', 'blur')})…")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3 * 3600, cwd=str(frame),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        log("Render quá lâu, bỏ qua và đăng bản gốc.")
        return video_file
    if proc.returncode != 0:
        detail = (proc.stdout + proc.stderr).strip().splitlines()
        log("Render lỗi: " + (detail[-1][:200] if detail else "không rõ") + ". Đăng bản gốc.")
        return video_file
    try:
        outputs = json.loads(proc.stdout.strip().splitlines()[-1]).get("outputs") or []
    except (ValueError, IndexError):
        outputs = []
    if outputs and Path(outputs[0]).is_file():
        log("Render xong.")
        return outputs[0]
    return str(expected) if expected.is_file() else video_file
