"""Tìm trình duyệt trên máy và lỗi mở cửa sổ có thể xử lý được."""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

BROWSERS = {
    "chrome": {"label": "Google Chrome", "engine": "chromium", "channel": "chrome"},
    "msedge": {"label": "Microsoft Edge", "engine": "chromium", "channel": "msedge"},
    "firefox": {"label": "Mozilla Firefox", "engine": "firefox", "channel": None},
    "chromium": {"label": "Chromium (đi kèm tool)", "engine": "chromium", "channel": None},
}
DEFAULT_BROWSER = "chrome"


class BrowserLaunchError(RuntimeError):
    def __init__(self, message, code="BROWSER_LAUNCH_FAILED"):
        super().__init__(message)
        self.code = code


def normalize_browser(kind):
    return kind if kind in BROWSERS else DEFAULT_BROWSER


def _registry_paths(kind):
    try:
        import winreg
    except ImportError:
        return []
    paths = []
    exe = "chrome.exe" if kind == "chrome" else "msedge.exe"
    key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for flag in (0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)):
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | flag) as handle:
                    value, _ = winreg.QueryValueEx(handle, None)
                    if isinstance(value, str):
                        paths.append(Path(os.path.expandvars(value.strip().strip('"'))))
            except OSError:
                continue
    return paths


def chromium_path(kind, system=None):
    if kind not in ("chrome", "msedge"):
        return None
    system = system or platform.system()
    candidates = []
    if system == "Windows":
        parts = ("Google", "Chrome", "Application", "chrome.exe") if kind == "chrome" else ("Microsoft", "Edge", "Application", "msedge.exe")
        for var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "ProgramW6432"):
            if os.environ.get(var):
                candidates.append(Path(os.environ[var]).joinpath(*parts))
        candidates.extend(_registry_paths(kind))
        executable = shutil.which("chrome.exe" if kind == "chrome" else "msedge.exe")
    elif system == "Darwin":
        app, exe = ("Google Chrome", "Google Chrome") if kind == "chrome" else ("Microsoft Edge", "Microsoft Edge")
        candidates.extend(base / (app + ".app") / "Contents" / "MacOS" / exe
                          for base in (Path("/Applications"), Path.home() / "Applications"))
        executable = shutil.which("google-chrome" if kind == "chrome" else "microsoft-edge")
    else:
        executable = shutil.which("google-chrome" if kind == "chrome" else "microsoft-edge")
    if executable:
        candidates.append(Path(executable))
    return next((str(p.resolve()) for p in candidates if p.is_file()), None)


def preferred_browser():
    return next((k for k in ("chrome", "msedge") if chromium_path(k)), "chromium")


def launch_error(error, kind):
    if isinstance(error, BrowserLaunchError):
        return error
    label = BROWSERS[normalize_browser(kind)]["label"]
    low = str(error).lower()
    if isinstance(error, PermissionError):
        return BrowserLaunchError("Không ghi được hồ sơ trình duyệt. Giải nén tool vào thư mục có quyền ghi, rồi chạy lại.", "PROFILE_NOT_WRITABLE")
    if any(s in low for s in ("processsingleton", "singletonlock", "user data directory is already in use", "profile is in use", "profile in use", "another instance", "parent.lock")):
        return BrowserLaunchError("Hồ sơ tài khoản đang được một cửa sổ/tool khác sử dụng. Đóng cửa sổ đó rồi thử lại. Không cần xóa hồ sơ.", "PROFILE_IN_USE")
    if any(s in low for s in ("executable doesn't exist", "executable does not exist", "playwright install")):
        return BrowserLaunchError(f"Chưa có bản {label} phù hợp với Playwright. Đóng tool và chạy lại setup.bat để cài trình duyệt đi kèm.", "BROWSER_NOT_INSTALLED")
    if "timeout" in low or "timed out" in low:
        return BrowserLaunchError(f"Quá thời gian mở {label}. Đóng cửa sổ của tài khoản còn mở rồi thử lại, hoặc chọn Chromium và đăng nhập lại.", "BROWSER_LAUNCH_TIMEOUT")
    return BrowserLaunchError(f"Không mở được {label}. Chạy lại setup.bat; nếu vẫn lỗi, chọn Chromium (đi kèm tool) hoặc xem Nhật ký kết nối.")
