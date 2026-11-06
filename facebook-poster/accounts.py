"""Cấu hình Facebook theo tài khoản; chuyển dữ liệu v8 sang v9 một lần."""
from __future__ import annotations

import copy
import re
import uuid
from urllib.parse import parse_qs, urlparse

ACCOUNT_DEFAULTS = {
    "browser": "chrome", "account": None, "pages": [], "available_pages": [],
    "slots": ["08:00", "12:00", "20:00"], "caption": "{title}\n\n{hashtags}",
    "hashtags": "", "enabled": False, "fired": {}, "schedule_reviewed": False,
    "keywords": [], "reading": False, "last_read": 0,
}


def new_account(label: str, browser: str = "chrome", account_id: str | None = None) -> dict:
    return {**copy.deepcopy(ACCOUNT_DEFAULTS), "id": account_id or uuid.uuid4().hex,
            "label": label.strip() or "Tài khoản Facebook", "browser": browser}


def migrate(data: dict) -> dict:
    """Giữ lịch sử/chống trùng và dùng lại hồ sơ fb-profile/<browser> của v8.

    ID `default` dành riêng cho tài khoản cũ. Tài khoản mới dùng UUID và thư mục
    fb-profile/accounts/<id>/<browser>; không sao chép cookie giữa tài khoản.
    """
    if "accounts" not in data:
        old = new_account((data.get("account") or {}).get("name") or "Tài khoản 1", account_id="default")
        for key in ACCOUNT_DEFAULTS:
            if key in data:
                old[key] = copy.deepcopy(data[key])
        data["accounts"] = [old]
        data["selected_account_id"] = old["id"]
        for post in data.get("posts", {}).values():
            post.setdefault("account_id", "default")
        data["schema_version"] = 9
    # Không để cấu hình toàn cục cũ vô tình được dùng cho tài khoản khác.
    for key in ACCOUNT_DEFAULTS:
        data.pop(key, None)
    if data.get("selected_account_id") not in {a["id"] for a in data["accounts"]}:
        data["selected_account_id"] = next((a["id"] for a in data["accounts"]), None)
    return data


def account_for(data: dict, account_id: str | None = None) -> dict:
    target = account_id or data.get("selected_account_id")
    account = next((a for a in data["accounts"] if a["id"] == target), None)
    if account is None:
        raise ValueError("Tài khoản không còn tồn tại. Chọn hoặc thêm tài khoản Facebook.")
    return account


def facebook_url(value: str) -> bool:
    try:
        u = urlparse(value)
        host = (u.hostname or "").lower()
        return (u.scheme == "https" and not u.username and not u.password and not u.port
                and (host == "facebook.com" or host.endswith(".facebook.com")))
    except ValueError:
        return False


def page_key(page: dict) -> str:
    """Chuẩn hóa liên kết để gắn Page đã quét với lịch đăng (không đoán quyền)."""
    u = urlparse(page["url"])
    numeric = (parse_qs(u.query).get("id") or [None])[0]
    if numeric and numeric.isdigit():
        return numeric
    return u.path.strip("/").lower()


def selected_pages(account: dict, urls: list[str]) -> list[dict]:
    """Chỉ chọn Page đã quét từ tài khoản, không nhận tên/link tùy ý từ UI."""
    if not isinstance(urls, list) or any(not isinstance(u, str) for u in urls):
        raise ValueError("Danh sách Page không hợp lệ.")
    available = {p["url"]: p for p in account["available_pages"]}
    if any(url not in available for url in urls):
        raise ValueError("Page không thuộc danh sách đã quét của tài khoản này. Quét Page lại.")
    return [copy.deepcopy(available[url]) for url in dict.fromkeys(urls)]


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("ID tài khoản không hợp lệ.")
    return value
