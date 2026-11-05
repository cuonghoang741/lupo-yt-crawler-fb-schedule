"""Module 3 — Upload Facebook.

Đăng video (bản đã render nếu có, nếu không thì bản gốc) lên các Page, kiểm tra tài
khoản và đọc tin. Lớp vỏ gọn quanh fbpost để tách rõ bước đăng khỏi cào và render.
"""
from __future__ import annotations

import fbpost

# Dùng lại nguyên các lớp/lỗi của fbpost để engine chỉ cần nói chuyện với module này.
Session = fbpost.Session
AuthRequired = fbpost.AuthRequired
Uncertain = fbpost.Uncertain
login_until_closed = fbpost.login_until_closed
