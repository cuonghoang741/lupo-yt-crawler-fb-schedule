"""Facebook Poster — đăng video (chọn file từ máy) lên Page Facebook, nhiều tài khoản, đăng tay.

Không tải YouTube, không tự động: chọn video → chọn tài khoản + Page → bấm Đăng.
"""
from __future__ import annotations

import json
import copy
import os
import queue
import subprocess
import sys
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from browser_support import BrowserLaunchError, preferred_browser

BUILD = "2026.11.06.1"

import accounts
import fbpost
import ytcore

ROOT = ytcore.app_dir()
STATE = ROOT / "accounts.json"
STATES = {"posted": "Đã đăng", "uncertain": "Cần kiểm tra", "posting": "Đang đăng",
          "preparing": "Đang chuẩn bị", "failed": "Lỗi"}
ACTIVITY = {"login": "Đang chờ đăng nhập Facebook…", "check": "Đang kiểm tra tài khoản…",
            "scan": "Đang quét Page quản lý…", "post": "Đang đăng bài…", "lookup": "Đang tìm bài trên Page…"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}


class Store:
    def __init__(self, path=STATE):
        self.path = path
        self.lock = threading.RLock()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        fresh = not data
        data.setdefault("posts", {})
        self.data = accounts.migrate(data)
        if fresh:
            self.account()["browser"] = preferred_browser()

    def save(self):
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    def account(self, account_id=None):
        return accounts.account_for(self.data, account_id)

    def update_account(self, account_id, **values):
        with self.lock:
            self.account(account_id).update(values)
            self.save()

    def set_post(self, key, **values):
        with self.lock:
            self.data["posts"][key] = {**self.data["posts"].get(key, {}), **values}
            self.save()


class Api:
    def __init__(self, store=None, start_worker=True):
        self.store = store or Store()
        self.logs: deque[str] = deque(maxlen=300)
        self.commands: queue.Queue = queue.Queue()
        self.current = None
        self.current_account_id = None
        self.pending_connections = set()
        self.compose_file = ""
        self.dialog = None
        self.stop = threading.Event()
        for account in self.store.data["accounts"]:
            if (account.get("connection") or {}).get("state") in ("queued", "opening", "login", "checking"):
                account["connection"] = {"state": "idle", "message": "Lượt kết nối trước đã dừng. Bấm Mở lại trình duyệt để tiếp tục."}
        for post in self.store.data["posts"].values():  # phục hồi trạng thái dở sau khi tắt app
            if post.get("state") == "posting":
                post.update(state="uncertain", error="App tắt sau khi bấm Đăng. Kiểm tra Page.")
            elif post.get("state") == "preparing":
                post.update(state="failed", error="App tắt trước khi bấm Đăng.")
        self.store.save()
        if start_worker:
            threading.Thread(target=self._run, daemon=True).start()

    # ---------- worker ----------
    def log(self, m):
        now = datetime.now()
        self.logs.append(f"{now:%H:%M} {m}")
        try:
            folder = self.store.path.parent / "logs"
            folder.mkdir(exist_ok=True)
            with (folder / f"facebook-poster-{now:%Y-%m-%d}.log").open("a", encoding="utf-8") as f:
                f.write(f"{now:%H:%M:%S} {m}\n")
        except OSError:
            pass

    def connection(self, account_id, state, message, code=None):
        self.store.update_account(account_id, connection={"state": state, "message": message, "code": code})

    def _run(self):
        while not self.stop.is_set():
            try:
                cmd = self.commands.get(timeout=1)
            except queue.Empty:
                continue
            self.current = cmd[0]
            self.current_account_id = cmd[1]
            try:
                self._handle(*cmd)
            except Exception as e:
                if cmd[0] in ("login", "open_browser", "check"):
                    state = self.store.account(cmd[1]).get("connection", {}).get("state")
                    error = (BrowserLaunchError("Trình duyệt đã mở nhưng chưa kiểm tra được phiên Facebook. Kiểm tra mạng rồi bấm Kiểm tra lại.", "SESSION_CHECK_FAILED")
                             if state == "checking" else fbpost.launch_error(e, self.store.account(cmd[1])["browser"]))
                    self.connection(cmd[1], "error", str(error), error.code)
                    self.log(f"[{error.code}] {error}")
                else:
                    self.log(f"Lỗi: {e}")
            finally:
                if cmd[0] in ("login", "open_browser"):
                    self.pending_connections.discard(cmd[1])
                self.current = None
                self.current_account_id = None
                self.commands.task_done()

    def _session(self, account):
        s = fbpost.Session(False, account["browser"], account["id"])
        try:
            if not (account.get("account") or {}).get("ok"):
                raise fbpost.AuthRequired("Kiểm tra/đăng nhập tài khoản trước.")
            s.assert_identity((account["account"] or {}).get("id"))
            return s
        except Exception:
            s.close()
            raise

    def _auth_failed(self, account_id, msg):
        self.store.update_account(account_id, account={**(self.store.account(account_id).get("account") or {}),
                                                        "ok": False, "checked_at": datetime.now().isoformat(timespec="minutes")})
        self.log(msg)

    def _handle(self, kind, account_id, *args):
        account = self.store.account(account_id)
        if kind in ("login", "open_browser"):
            label = fbpost.BROWSERS[account["browser"]]["label"]
            self.connection(account_id, "opening", f"Đang mở {label}…")
            self.log(f"[{account['label']}] Đang mở {label}.")
            def opened():
                message = "Đã mở trình duyệt. Đăng nhập/xác minh Facebook rồi đóng cửa sổ đó để lưu phiên."
                self.connection(account_id, "login", message)
                self.log(f"[{account['label']}] {message}")
            fbpost.login_until_closed(kind=account["browser"], account_id=account_id,
                                      on_open=opened, should_stop=self.stop.is_set)
            if self.stop.is_set():
                return
            return self._check(account_id)
        if kind == "check":
            return self._check(account_id)
        if kind == "scan":
            return self._scan(account_id)
        if kind == "post":
            return self._post(account_id, *args)
        if kind == "lookup":
            return self._lookup(*args)

    def _check(self, account_id):
        account = self.store.account(account_id)
        self.connection(account_id, "checking", "Cửa sổ đã đóng. Đang kiểm tra phiên Facebook…")
        try:
            with fbpost.Session(False, account["browser"], account_id) as s:
                ident = s.account()
            previous = (account.get("account") or {}).get("id")
            if previous and previous != ident["id"]:
                raise fbpost.AuthRequired("Hồ sơ đang đăng nhập tài khoản Facebook khác. Đăng nhập đúng tài khoản hoặc thêm tài khoản mới.")
            self.store.update_account(account_id, account={**ident, "ok": True,
                                      "checked_at": datetime.now().isoformat(timespec="minutes")})
            self.log(f"[{account['label']}] Đã đăng nhập: {ident.get('name') or ident.get('id')}.")
            self.connection(account_id, "ready", "Đã lưu và kiểm tra phiên Facebook.")
        except fbpost.AuthRequired as e:
            self._auth_failed(account_id, f"[{account['label']}] Chưa đăng nhập hoặc cần xác minh.")
            self.connection(account_id, "error", str(e) or "Facebook chưa đăng nhập hoặc cần xác minh. Bấm Đăng nhập Facebook để mở lại.", "AUTH_REQUIRED")

    def _scan(self, account_id):
        account = self.store.account(account_id)
        try:
            with self._session(account) as s:
                pages = s.managed_pages()
            self.store.update_account(account_id, available_pages=pages,
                                      pages_checked_at=datetime.now().isoformat(timespec="minutes"), pages_error=None)
            self.log(f"[{account['label']}] Đã quét {len(pages)} Page quản lý.")
        except fbpost.AuthRequired:
            self._auth_failed(account_id, f"[{account['label']}] Facebook yêu cầu đăng nhập lại.")
        except Exception as e:
            self.store.update_account(account_id, pages_error=str(e)[:300])
            self.log(f"[{account['label']}] Quét Page lỗi: {e}")

    def _post(self, account_id, file, page_urls, caption):
        account = self.store.account(account_id)
        avail = {p["url"]: p for p in account["available_pages"]}
        pages = [avail[u] for u in page_urls if u in avail]
        if not pages:
            return self.log("Không có Page hợp lệ để đăng.")
        if not Path(file).is_file():
            return self.log("File video không tồn tại.")
        self.log(f"[{account['label']}] Đăng “{Path(file).name}” lên {len(pages)} Page.")
        try:
            session = self._session(account)
        except fbpost.AuthRequired as e:
            return self._auth_failed(account_id, str(e))
        except Exception as e:
            return self.log(f"Không mở được trình duyệt: {e}")
        try:
            for page in pages:
                key = uuid.uuid4().hex
                self.store.set_post(key, state="preparing", title=Path(file).name, page=page["name"],
                                    at=datetime.now().isoformat(timespec="minutes"), account_id=account_id,
                                    account_label=account["label"], page_url=page["url"], file=file, caption=caption, error=None)
                try:
                    pid = session.switch_page(page)
                    url = session.publish(file, caption, page, pid,
                                          lambda: self.store.set_post(key, state="posting", page_id=pid), self.log)
                    self.store.set_post(key, state="posted", url=url, error=None)
                    self.log(f"Đã đăng lên {page['name']}: {url}")
                except fbpost.AuthRequired:
                    st = "uncertain" if self.store.data["posts"][key]["state"] == "posting" else "failed"
                    self.store.set_post(key, state=st, error="Facebook yêu cầu đăng nhập/xác minh lại.")
                    self._auth_failed(account_id, "Facebook yêu cầu đăng nhập lại. Dừng đăng.")
                    return
                except fbpost.Uncertain as e:
                    self.store.set_post(key, state="uncertain", error=str(e))
                    self.log(f"{page['name']}: {e}")
                except Exception as e:
                    st = "uncertain" if self.store.data["posts"][key]["state"] == "posting" else "failed"
                    self.store.set_post(key, state=st, error=str(e)[:300])
                    self.log(f"{page['name']}: {str(e)[:200]}")
        finally:
            session.close()

    def _lookup(self, key):
        post = self.store.data["posts"].get(key)
        if not post:
            return
        account = self.store.account(post.get("account_id"))
        page = {"name": post.get("page", ""), "url": post.get("page_url", "")}
        try:
            with self._session(account) as s:
                pid = s.switch_page(page)
                url = s.lookup(page, pid, post.get("caption") or "")
            if url:
                self.store.set_post(key, state="posted", url=url, error=None)
                self.log(f"Tìm thấy bài trên {page['name']}: {url}")
            else:
                self.log(f"Chưa thấy bài trên {page['name']}. Mở Page kiểm tra bằng mắt.")
        except Exception as e:
            self.log(f"Tìm lại lỗi: {e}")

    # ---------- snapshot ----------
    def snapshot(self):
        with self.store.lock:
            d = copy.deepcopy(self.store.data)
        sel = d.get("selected_account_id")
        acc = accounts.account_for(d, sel) if sel else None
        posts = sorted(d["posts"].items(), key=lambda kv: kv[1].get("at") or "", reverse=True)
        return {
            "build": BUILD,
            "accounts": [{"id": a["id"], "label": a["label"], "browser": a["browser"],
                          "ok": bool((a.get("account") or {}).get("ok")),
                          "name": (a.get("account") or {}).get("name"),
                          "pages": len(a["available_pages"])} for a in d["accounts"]],
            "selected_account_id": sel,
            "account": (acc.get("account") if acc else None),
            "available_pages": acc["available_pages"] if acc else [],
            "pages_error": acc.get("pages_error") if acc else None,
            "pages_checked_at": acc.get("pages_checked_at") if acc else None,
            "browser": acc["browser"] if acc else "chrome",
            "preferred_browser": preferred_browser(),
            "connection": acc.get("connection") if acc else None,
            "connection_busy": sel in self.pending_connections,
            "browsers": [{"id": k, "label": v["label"]} for k, v in fbpost.BROWSERS.items()],
            "compose_file": self.compose_file,
            "busy": self.current is not None, "activity": ACTIVITY.get(self.current or ""),
            "posts": [{"key": k, "at": (p.get("at") or "").replace("T", " "), "title": p.get("title", ""),
                       "page": p.get("page", ""), "account": p.get("account_label", ""), "state": p.get("state", ""),
                       "state_text": STATES.get(p.get("state"), p.get("state", "")), "url": p.get("url"),
                       "error": p.get("error"), "file": p.get("file")} for k, p in posts[:300]],
            "log": list(self.logs)[-150:],
        }

    # ---------- actions ----------
    def action(self, req):
        fn = getattr(self, "do_" + (req.get("action") or ""), None)
        if not fn:
            raise ValueError("Thao tác không hợp lệ.")
        return fn(req) or {"ok": True}

    def _acc_id(self, req):
        return self.store.account(req.get("account_id"))["id"]

    def do_add_account(self, req):
        label = (req.get("label") or "").strip() or f"Tài khoản {len(self.store.data['accounts']) + 1}"
        browser = fbpost.normalize_browser(req.get("browser") or preferred_browser())
        acc = accounts.new_account(label, browser)
        with self.store.lock:
            self.store.data["accounts"].append(acc)
            self.store.data["selected_account_id"] = acc["id"]
            self.store.save()
        return {"ok": True, "account_id": acc["id"]}

    def do_remove_account(self, req):
        self._require_idle()
        aid = req.get("account_id")
        with self.store.lock:
            self.store.data["accounts"] = [a for a in self.store.data["accounts"] if a["id"] != aid]
            if self.store.data["selected_account_id"] == aid:
                self.store.data["selected_account_id"] = next((a["id"] for a in self.store.data["accounts"]), None)
            self.store.save()
        return {"ok": True}

    def do_select_account(self, req):
        aid = self.store.account(req.get("account_id"))["id"]
        self.store.data["selected_account_id"] = aid
        self.store.save()
        return {"ok": True}

    def do_set_browser(self, req):
        account = self.store.account(self._acc_id(req))
        kind = fbpost.normalize_browser(req.get("browser"))
        if account["browser"] == kind:
            return {"ok": True}
        self._require_idle()
        self.store.update_account(account["id"], browser=kind, connection=None,
                                  account={**(account.get("account") or {}), "ok": False})
        return {"ok": True}

    def _require_idle(self):
        if self.current is not None or self.pending_connections or not self.commands.empty():
            raise ValueError("Đợi thao tác đang chạy xong và đóng cửa sổ đăng nhập trước khi đổi trình duyệt/xóa tài khoản.")

    def _open_connection(self, req, kind):
        aid = self._acc_id(req)
        with self.store.lock:
            if aid in self.pending_connections:
                return {"ok": True, "already_opening": True}
            if req.get("browser"):
                self.do_set_browser(req)
            browser = self.store.account(aid)["browser"]
            if fbpost.BROWSERS[browser]["channel"] and not fbpost.chromium_path(browser):
                error = BrowserLaunchError(f"Không tìm thấy {fbpost.BROWSERS[browser]['label']}. Chọn Chromium (đi kèm tool) rồi đăng nhập lại, hoặc cài trình duyệt này.", "BROWSER_NOT_FOUND")
                self.connection(aid, "error", str(error), error.code)
                self.log(f"[{error.code}] {error}")
                raise error
            self.connection(aid, "queued", "Đã nhận lệnh mở trình duyệt. Đợi thao tác hiện tại xong nếu có.")
            self.pending_connections.add(aid)
            self.commands.put((kind, aid))
        return {"ok": True}

    def do_login(self, req):
        return self._open_connection(req, "login")

    def do_open_browser(self, req):
        return self._open_connection(req, "open_browser")

    def do_check_account(self, req):
        aid = self._acc_id(req)
        if aid in self.pending_connections:
            return {"ok": True}
        self.commands.put(("check", aid))
        return {"ok": True}

    def do_scan_pages(self, req):
        self.commands.put(("scan", self._acc_id(req)))
        return {"ok": True}

    def do_add_page(self, req):
        account = self.store.account(req.get("account_id"))
        name = (req.get("name") or "").strip()
        url = (req.get("url") or "").strip().split("#")[0]
        if not name:
            raise ValueError("Nhập tên Page.")
        if not accounts.facebook_url(url):
            raise ValueError("Link Page phải là https://www.facebook.com/...")
        page = {"name": name, "url": url}
        with self.store.lock:
            avail = account["available_pages"]
            if any(accounts.page_key(p) == accounts.page_key(page) for p in avail):
                raise ValueError("Page này đã có trong danh sách.")
            account["available_pages"] = avail + [page]
            self.store.save()
        return {"ok": True}

    def do_remove_page(self, req):
        account = self.store.account(req.get("account_id"))
        with self.store.lock:
            account["available_pages"] = [p for p in account["available_pages"] if p["url"] != req.get("url")]
            self.store.save()
        return {"ok": True}

    def do_pick_file(self, req):
        if not self.dialog:
            raise ValueError("Không mở được hộp thoại chọn file.")
        picked = self.dialog("file")
        if picked and Path(picked).suffix.lower() in VIDEO_EXTS:
            self.compose_file = picked
        return {"ok": True, "file": self.compose_file}

    def do_post(self, req):
        account = self.store.account(req.get("account_id"))
        file = (req.get("file") or self.compose_file or "").strip()
        if not file or not Path(file).is_file():
            raise ValueError("Chọn một file video trước.")
        urls = req.get("page_urls") or []
        avail = {p["url"] for p in account["available_pages"]}
        urls = [u for u in urls if u in avail]
        if not urls:
            raise ValueError("Chọn ít nhất một Page của tài khoản này.")
        caption = (req.get("caption") or "").strip()
        if not caption:
            raise ValueError("Nhập nội dung bài đăng.")
        if not (account.get("account") or {}).get("ok"):
            raise ValueError("Tài khoản chưa đăng nhập. Đăng nhập trước.")
        self.commands.put(("post", account["id"], file, urls, caption))
        return {"ok": True}

    def do_lookup(self, req):
        self.commands.put(("lookup", self.store.data.get("selected_account_id"), req.get("key")))
        return {"ok": True}

    def do_mark_posted(self, req):
        url = (req.get("url") or "").strip()
        if not (url.startswith("https://") and "facebook.com" in url):
            raise ValueError("Link phải là link bài Facebook.")
        self.store.set_post(req.get("key"), state="posted", url=url, error=None)
        return {"ok": True}

    def do_allow_retry(self, req):
        post = self.store.data["posts"].get(req.get("key"))
        if not post or post.get("state") not in ("uncertain", "failed"):
            raise ValueError("Chỉ dùng cho bài Cần kiểm tra hoặc Lỗi.")
        self.store.set_post(req.get("key"), state="failed", error="Có thể đăng lại.")
        return {"ok": True}

    def do_open(self, req):
        u = req.get("path")
        if u:
            if u.startswith("http"):
                import webbrowser
                webbrowser.open(u)
            elif Path(u).exists():
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", u], check=False) if os.name != "nt" else os.startfile(u)  # noqa
        return {"ok": True}

    def shutdown(self):
        self.stop.set()


def main():
    (ROOT / "logs").mkdir(exist_ok=True)
    import webserver
    webserver.run(Api(), "Facebook Poster", width=1120, height=800)


if __name__ == "__main__":
    main()
