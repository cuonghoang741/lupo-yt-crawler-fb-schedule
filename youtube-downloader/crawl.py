"""Module 1 — Tự cào + tải video.

Quét kênh YouTube tìm video mới và tải về máy. Chỉ là lớp vỏ gọn quanh ytcore để
ba bước của tool (cào+tải → render → đăng) tách thành ba module rõ ràng.
"""
from __future__ import annotations

from pathlib import Path

import ytcore

Cancelled = ytcore.Cancelled


def ensure_tools(report=lambda message, fraction=None: None) -> dict[str, str]:
    return ytcore.ensure_tools(report)


def resolve(channel: str) -> ytcore.YoutubeInput:
    """Chuẩn hóa một dòng người dùng nhập thành link kênh/video."""
    return ytcore.youtube_input(channel)


def list_videos(item: ytcore.YoutubeInput, tools: dict, on_video, should_stop, limit=None) -> int:
    """Liệt kê video của một kênh (gọi on_video cho từng video). limit = số video tối đa."""
    return ytcore.expand(item, tools, on_video, should_stop, limit)


def download(url: str, output: Path, height: int, tools: dict, on_progress, should_stop) -> dict:
    """Tải một video về output/<Kênh>/. Trả về {title, channel, file, size, skipped}."""
    return ytcore.download(url, output, height, tools, on_progress, should_stop)


def library(output: Path) -> list[dict]:
    """Danh sách video đã tải (đọc *.info.json), mỗi video kèm đường dẫn file trên máy."""
    return ytcore.scan_library(output)
