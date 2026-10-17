"""
LocalBot 管理後台（/admin）。

- 單一 HTML 頁面（admin_ui/index.html）+ JSON API（/admin/api/*），沒有任何外部相依。
- 以管理員密碼登入（LOCALBOT_ADMIN_PASSWORD；未設定時第一次啟動自動產生並存入金鑰檔）。
- 登入後使用簽章 Cookie（HttpOnly、SameSite=Strict、僅限 /admin 路徑），
  所有會改變資料的請求都要帶 X-CSRF-Token，登入失敗有次數限制。
- 本模組不直接 import app.py，而是由 app.py 呼叫 init_admin(app, <app 模組>) 注入，
  這樣測試替換 app.db 等物件時，後台也會跟著用替換後的版本。
"""
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from datetime import timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, Response, jsonify, request, send_from_directory, session

import localconfig as cfg
from localbot.utils import calculate_signature

logger = logging.getLogger("LocalBotAdmin")

UI_DIR = os.path.join(cfg.BASE_DIR, "admin_ui")
START_TIME = time.time()

bp = Blueprint("admin", __name__, url_prefix="/admin")


class _State:
    ctx = None  # app.py 模組


def c():
    return _State.ctx


# ============================================================================
# 共用工具
# ============================================================================
def _err(message: str, status: int = 400, **extra):
    return jsonify({"error": message, **extra}), status


def _json() -> dict:
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def _audit(action: str, **info):
    detail = " ".join(f"{k}={v}" for k, v in info.items())
    logger.info(f"[admin] {action} ip={request.remote_addr} {detail}".strip())


def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _pw_tag() -> str:
    """目前密碼的指紋：密碼一改，所有舊 session 立刻失效。"""
    return hmac.new(cfg.FLASK_SECRET_KEY.encode(), cfg.ADMIN_PASSWORD.encode(), hashlib.sha256).hexdigest()[:16]


# ============================================================================
# 登入失敗限制（每個來源 IP 5 分鐘 5 次；全站 10 分鐘 30 次，避免繞過反向代理）
# ============================================================================
_fail_lock = threading.Lock()
_fails = {}  # key -> [timestamp, ...]
_LIMITS = (("ip", 5, 300), ("*", 30, 600))


def reset_login_limiter():
    with _fail_lock:
        _fails.clear()


def _blocked_for(ip: str) -> int:
    """回傳還需等待幾秒；0 表示可以嘗試。"""
    now = time.time()
    wait = 0
    with _fail_lock:
        for kind, max_fails, window in _LIMITS:
            key = ip if kind == "ip" else "*"
            stamps = [t for t in _fails.get(key, []) if now - t < window]
            _fails[key] = stamps
            if len(stamps) >= max_fails:
                wait = max(wait, int(stamps[0] + window - now) + 1)
    return wait


def _record_fail(ip: str):
    now = time.time()
    with _fail_lock:
        for key in (ip, "*"):
            _fails.setdefault(key, []).append(now)


def _clear_fails(ip: str):
    with _fail_lock:
        _fails.pop(ip, None)


def _check_password(value) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return hmac.compare_digest(value.encode("utf-8"), cfg.ADMIN_PASSWORD.encode("utf-8"))


def _verify_with_limit(value):
    """驗證密碼並套用失敗限制。回傳 (ok, 需等待秒數)。"""
    ip = request.remote_addr or "?"
    wait = _blocked_for(ip)
    if wait:
        return False, wait
    if _check_password(value):
        _clear_fails(ip)
        return True, 0
    _record_fail(ip)
    logger.warning(f"[admin] password check failed ip={ip}")
    return False, 0


def _too_many(wait: int):
    resp = jsonify({"error": f"嘗試次數過多，請 {wait} 秒後再試", "retryAfter": wait})
    resp.status_code = 429
    resp.headers["Retry-After"] = str(wait)
    return resp


# ============================================================================
# 驗證 / CSRF
# ============================================================================
def _authed() -> bool:
    if not session.get("admin"):
        return False
    if time.time() - session.get("iat", 0) >= cfg.ADMIN_SESSION_HOURS * 3600:
        return False
    return hmac.compare_digest(str(session.get("pw", "")), _pw_tag())


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _authed():
            return _err("未登入或登入已過期", 401)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            token = request.headers.get("X-CSRF-Token", "")
            if not token or not hmac.compare_digest(token, str(session.get("csrf", ""))):
                return _err("CSRF token 無效，請重新整理頁面", 403)
        return fn(*args, **kwargs)
    return wrapper


@bp.after_request
def _headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


# ============================================================================
# 頁面
# ============================================================================
@bp.route("", strict_slashes=False)
def index():
    path = os.path.join(UI_DIR, "index.html")
    try:
        with open(path, "r", encoding="utf-8") as f:
            html_text = f.read()
    except OSError:
        return Response("admin_ui/index.html not found", status=500, mimetype="text/plain")
    nonce = secrets.token_urlsafe(16)
    resp = Response(html_text.replace("__NONCE__", nonce), mimetype="text/html")
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
        "img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    return resp


# ============================================================================
# 登入 / 登出
# ============================================================================
@bp.post("/api/login")
def login():
    ok, wait = _verify_with_limit(_json().get("password"))
    if wait:
        return _too_many(wait)
    if not ok:
        return _err("密碼錯誤", 401)
    session.clear()
    session.permanent = True
    session["admin"] = True
    session["iat"] = time.time()
    session["pw"] = _pw_tag()
    session["csrf"] = secrets.token_urlsafe(24)
    _audit("login")
    return jsonify({"ok": True, "csrf": session["csrf"]})


@bp.get("/api/session")
def session_info():
    if _authed():
        return jsonify({"authenticated": True, "csrf": session["csrf"]})
    return jsonify({"authenticated": False})


@bp.post("/api/logout")
@admin_required
def logout():
    _audit("logout")
    session.clear()
    return jsonify({"ok": True})


# ============================================================================
# 儀表板
# ============================================================================
def _online_ids() -> set:
    return {uid for uid, sids in list(c().connected_users.items()) if sids}


def _bot_filter():
    """?botId= 篩選（可省略）。回傳 (bot_id 或 None, 錯誤回應)。"""
    value = request.args.get("botId") or None
    if value is None:
        return None, None
    if not c().is_safe_id(value) or c().db.get_bot(value) is None:
        return None, _err("找不到這個 Bot", 404)
    return value, None


def _bot_names() -> dict:
    return {b["bot_id"]: b["name"] for b in c().db.list_bots()}


@bp.get("/api/stats")
@admin_required
def stats():
    db = c().db
    bot_id, err = _bot_filter()
    if err:
        return err
    data = db.stats(bot_id)
    data["online"] = len(_online_ids())
    data["daily"] = db.message_counts_by_day(7, bot_id)
    data["uptimeSeconds"] = int(time.time() - START_TIME)
    data["defaultRichMenuId"] = db.get_setting(c().default_richmenu_key(bot_id)) if bot_id else None
    data.update(db.automation_stats(bot_id))
    data["serverTime"] = int(time.time() * 1000)
    return jsonify(data)


# ============================================================================
# 使用者
# ============================================================================
def _key_status(row: dict) -> str:
    if row.get("has_key"):
        return "active"
    return "revoked" if row.get("revoked_at") else "none"


def _user_view(row: dict, online: set) -> dict:
    return {
        "userId": row["user_id"],
        "displayName": row.get("display_name") or "",
        "createdAt": row.get("created_at"),
        "lastSeenAt": row.get("last_seen_at"),
        "keyStatus": _key_status(row),
        "bots": row.get("bots", []),
        "messageCount": row.get("message_count", 0),
        "lastMessageAt": row.get("last_message_at"),
        "online": row["user_id"] in online,
    }


def _get_user_or_404(user_id):
    if not c().is_safe_id(user_id):
        return None, _err("使用者 ID 格式不正確", 400)
    user = c().db.get_user(user_id)
    if not user:
        return None, _err("找不到這位使用者", 404)
    return user, None


def _user_row(user_id: str):
    rows = c().db.list_users(q=user_id, limit=200)["users"]
    return next((u for u in rows if u["user_id"] == user_id), None)


@bp.get("/api/users")
@admin_required
def users_list():
    bot_id, err = _bot_filter()
    if err:
        return err
    result = c().db.list_users(
        q=(request.args.get("q") or "").strip()[:64] or None,
        limit=_int_arg("limit", 50, 1, 200),
        offset=_int_arg("offset", 0, 0, 10 ** 9),
        bot_id=bot_id,
    )
    online = _online_ids()
    return jsonify({"total": result["total"], "users": [_user_view(u, online) for u in result["users"]]})


@bp.get("/api/users/<user_id>")
@admin_required
def user_get(user_id):
    user, err = _get_user_or_404(user_id)
    if err:
        return err
    view = _user_view(_user_row(user_id), _online_ids())
    for m in view["bots"]:
        m["richMenuId"] = c().db.get_user_richmenu_id(m["botId"], user_id)
    return jsonify(view)


@bp.patch("/api/users/<user_id>")
@admin_required
def user_update(user_id):
    user, err = _get_user_or_404(user_id)
    if err:
        return err
    data = _json()
    if "displayName" in data:
        name = data["displayName"]
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 64):
            return _err("顯示名稱需為 1～64 個字")
        c().db.update_display_name(user_id, name.strip())
    if "blocked" in data:
        if not isinstance(data["blocked"], bool):
            return _err("blocked 必須是布林值")
        bot_id = data.get("botId")
        membership = c().db.get_membership(bot_id, user_id) if isinstance(bot_id, str) else None
        if membership is None:
            return _err("這位使用者不是該 Bot 的好友", 404)
        blocked = data["blocked"]
        if membership["blocked"] != blocked:
            c().db.set_blocked(bot_id, user_id, blocked)
            # 與使用者自己封鎖時相同：通知 Bot（unfollow / follow）
            if blocked:
                c().send_platform_event(bot_id, user_id, "unfollow")
            else:
                c().send_platform_event(bot_id, user_id, "follow", follow={"isUnblocked": True})
            c().notify_richmenu_changed(bot_id, [user_id])
    _audit("user.update", user=user_id, fields=",".join(k for k in data if k in ("displayName", "blocked")))
    return jsonify({"ok": True})


@bp.post("/api/users/<user_id>/revoke")
@admin_required
def user_revoke(user_id):
    """撤銷這位使用者（裝置）的金鑰：立刻中斷連線；要重新用邀請碼加入才能再使用。其他人不受影響。"""
    user, err = _get_user_or_404(user_id)
    if err:
        return err
    if _json().get("confirm") is not True:
        return _err("撤銷金鑰需要 confirm: true")
    c().db.revoke_user_token(user_id)
    c().disconnect_user(user_id)
    _audit("user.revoke", user=user_id)
    return jsonify({"ok": True})


@bp.delete("/api/users/<user_id>/bots/<bot_id>")
@admin_required
def user_remove_from_bot(user_id, bot_id):
    """把使用者從某個 Bot 移除（刪除好友關係與該 Bot 的對話）。"""
    user, err = _get_user_or_404(user_id)
    if err:
        return err
    if not c().is_safe_id(bot_id) or c().db.get_membership(bot_id, user_id) is None:
        return _err("這位使用者不是該 Bot 的好友", 404)
    if not c().db.get_membership(bot_id, user_id)["blocked"]:
        c().send_platform_event(bot_id, user_id, "unfollow")
    c().db.remove_membership(bot_id, user_id)
    c().notify_richmenu_changed(bot_id, [user_id])
    _audit("user.remove_from_bot", user=user_id, bot=bot_id)
    return jsonify({"ok": True})


@bp.delete("/api/users/<user_id>")
@admin_required
def user_delete(user_id):
    user, err = _get_user_or_404(user_id)
    if err:
        return err
    c().db.delete_user(user_id)
    c().disconnect_user(user_id)
    _audit("user.delete", user=user_id)
    return jsonify({"ok": True})


# ============================================================================
# 訊息
# ============================================================================
def _summary(mtype: str, content) -> str:
    c_ = content if isinstance(content, dict) else {}
    alt = c_.get("altText") or ""
    if mtype == "text":
        text = c_.get("text") if c_ else content
        return str(text if text is not None else "")[:200]
    if mtype == "sticker":
        return f"[貼圖] {c_.get('packageId', '')}/{c_.get('stickerId', '')}"
    if mtype == "image":
        return "[圖片]"
    if mtype == "video":
        return "[影片]"
    if mtype == "audio":
        return "[語音]"
    if mtype == "file":
        return f"[檔案] {c_.get('fileName', '')}"
    if mtype == "location":
        return f"[位置] {c_.get('title', '')} {c_.get('address', '')}".strip()
    if mtype == "postback":
        return f"[Postback] {c_.get('data', '')}"[:200]
    if mtype in ("flex", "template", "imagemap"):
        return f"[{mtype}] {alt}"[:200]
    return f"[{mtype}]"


def _thumb(mtype: str, content):
    """只回傳本機 /media/ 路徑（避免後台載入外部圖片）。"""
    if mtype not in ("image", "video") or not isinstance(content, dict):
        return None
    provider = content.get("contentProvider") if isinstance(content.get("contentProvider"), dict) else {}
    for url in (content.get("previewImageUrl"), content.get("originalContentUrl"),
                provider.get("previewImageUrl"), provider.get("originalContentUrl")):
        if isinstance(url, str):
            path = urlparse(url).path
            if path.startswith("/media/") and ".." not in path:
                return path
    return None


def _msg_view(m: dict) -> dict:
    return {
        "id": m["id"],
        "messageId": m["message_id"],
        "botId": m.get("bot_id"),
        "botName": m.get("bot_name") or "",
        "userId": m["user_id"],
        "displayName": m.get("display_name") or "",
        "direction": m["direction"],
        "type": m["message_type"],
        "createdAt": m["created_at"],
        "summary": _summary(m["message_type"], m["content"]),
        "thumb": _thumb(m["message_type"], m["content"]),
        "content": m["content"],
    }


def _messages_response(**filters):
    before = request.args.get("beforeId")
    result = c().db.search_messages(
        limit=_int_arg("limit", 50, 1, 100),
        before_id=int(before) if before and before.isdigit() else None,
        **filters,
    )
    return jsonify({"messages": [_msg_view(m) for m in result["messages"]], "hasMore": result["hasMore"]})


@bp.get("/api/messages")
@admin_required
def messages_search():
    bot_id, err = _bot_filter()
    if err:
        return err
    return _messages_response(
        bot_id=bot_id,
        q=(request.args.get("q") or "").strip()[:100] or None,
        direction=request.args.get("direction") or None,
        message_type=(request.args.get("type") or "")[:32] or None,
        user=(request.args.get("user") or "").strip()[:64] or None,
    )


@bp.get("/api/users/<user_id>/messages")
@admin_required
def user_messages(user_id):
    user, err = _get_user_or_404(user_id)
    if err:
        return err
    bot_id, err = _bot_filter()
    if err:
        return err
    return _messages_response(user_id=user_id, bot_id=bot_id)


def _bot_or_404(bot_id):
    if not isinstance(bot_id, str) or not c().is_safe_id(bot_id):
        return None, _err("請選擇 Bot", 400)
    bot = c().db.get_bot(bot_id)
    if not bot:
        return None, _err("找不到這個 Bot", 404)
    return bot, None


@bp.post("/api/send")
@admin_required
def send_text():
    """以某個 Bot 的身分傳送文字訊息給單一好友或這個 Bot 的全體好友（等同 push / broadcast）。"""
    data = _json()
    bot, err = _bot_or_404(data.get("botId"))
    if err:
        return err
    if not bot["enabled"]:
        return _err("這個 Bot 已停用", 409)
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return _err("請輸入訊息內容")
    if len(text) > 5000:
        return _err("文字訊息最多 5000 字")
    messages = [{"type": "text", "text": text}]
    target = data.get("target")
    if target == "user":
        user, err = _get_user_or_404(data.get("userId"))
        if err:
            return err
        membership = c().db.get_membership(bot["bot_id"], user["user_id"])
        if membership is None:
            return _err("這位使用者不是該 Bot 的好友", 404)
        if membership["blocked"]:
            return _err("這位使用者已封鎖，訊息不會送達", 409)
        ids = c().deliver_to_client(bot["bot_id"], user["user_id"], messages)
        _audit("send.user", bot=bot["bot_id"], user=user["user_id"], chars=len(text))
        return jsonify({"sent": 1, "messageIds": ids})
    if target == "broadcast":
        if data.get("confirm") is not True:
            return _err("廣播需要 confirm: true")
        user_ids = c().db.list_user_ids(bot["bot_id"])
        for uid in user_ids:
            c().deliver_to_client(bot["bot_id"], uid, messages)
        _audit("send.broadcast", bot=bot["bot_id"], users=len(user_ids), chars=len(text))
        return jsonify({"sent": len(user_ids)})
    return _err("target 必須是 user 或 broadcast")


# ============================================================================
# Rich Menu（每個 Bot 各自一組；選單 ID 全站唯一，所以大部分端點只需要選單 ID）
# ============================================================================
def _menu_view(menu: dict, default_id) -> dict:
    return {
        "richMenuId": menu["richMenuId"],
        "botId": menu["botId"],
        "name": menu.get("name"),
        "size": menu.get("size"),
        "selected": menu.get("selected"),
        "chatBarText": menu.get("chatBarText"),
        "areas": menu.get("areas", []),
        "hasImage": bool(menu.get("imageExt")),
        "isDefault": menu["richMenuId"] == default_id,
        "userCount": len(c().db.users_with_richmenu(menu["botId"], menu["richMenuId"])),
    }


def _menu_or_404(richmenu_id):
    if not isinstance(richmenu_id, str) or not c().is_safe_id(richmenu_id):
        return None, _err("Rich Menu ID 格式不正確", 400)
    menu = c().db.get_richmenu_any(richmenu_id)
    if not menu:
        return None, _err("找不到這個 Rich Menu", 404)
    return menu, None


def _remove_menu_image(menu: dict):
    if menu.get("imageExt"):
        try:
            os.remove(os.path.join(c().RICHMENU_DIR, f"{menu['richMenuId']}.{menu['imageExt']}"))
        except OSError:
            pass


def _default_key(bot_id: str) -> str:
    return c().default_richmenu_key(bot_id)


@bp.get("/api/richmenus")
@admin_required
def richmenus_list():
    bot, err = _bot_or_404(request.args.get("botId"))
    if err:
        return err
    db = c().db
    default_id = db.get_setting(_default_key(bot["bot_id"]))
    return jsonify({
        "botId": bot["bot_id"],
        "richmenus": [_menu_view(m, default_id) for m in db.list_richmenus(bot["bot_id"])],
        "aliases": [{"aliasId": a["richMenuAliasId"], "richMenuId": a["richMenuId"]}
                    for a in db.list_richmenu_aliases(bot["bot_id"])],
        "defaultRichMenuId": default_id,
    })


@bp.post("/api/richmenus")
@admin_required
def richmenu_create():
    data = _json()
    bot, err = _bot_or_404(data.get("botId"))
    if err:
        return err
    error = c().validate_richmenu(data)
    if error:
        return _err(error)
    richmenu_id = f"richmenu-{secrets.token_hex(16)}"
    c().db.create_richmenu(bot["bot_id"], richmenu_id,
                           {k: data[k] for k in ("size", "selected", "name", "chatBarText", "areas")})
    _audit("richmenu.create", bot=bot["bot_id"], id=richmenu_id)
    return jsonify({"richMenuId": richmenu_id})


@bp.post("/api/richmenus/<richmenu_id>/image")
@admin_required
def richmenu_upload(richmenu_id):
    menu, err = _menu_or_404(richmenu_id)
    if err:
        return err
    content_type = (request.content_type or "").split(";")[0].strip().lower()
    if content_type not in ("image/png", "image/jpeg"):
        return _err("圖片必須是 PNG 或 JPEG", 415)
    data = request.get_data()
    if not data:
        return _err("沒有收到圖片")
    if len(data) > c().RICHMENU_MAX_IMAGE_BYTES:
        return _err("圖片需在 1 MB 以內", 413)
    ext = c()._detect_image(data)
    if ext is None:
        return _err("檔案內容不是有效的 PNG 或 JPEG")
    path = os.path.join(c().RICHMENU_DIR, f"{richmenu_id}.{ext}")
    with open(path, "wb") as f:
        f.write(data)
    if menu.get("imageExt") and menu["imageExt"] != ext:
        _remove_menu_image(menu)  # 換了格式：移除舊圖
    c().db.set_richmenu_image(richmenu_id, ext)
    bot_id = menu["botId"]
    is_default = c().db.get_setting(_default_key(bot_id)) == richmenu_id
    c().notify_richmenu_changed(bot_id, None if is_default else c().db.users_with_richmenu(bot_id, richmenu_id))
    _audit("richmenu.image", id=richmenu_id, bytes=len(data))
    return jsonify({"ok": True})


@bp.get("/api/richmenus/<richmenu_id>/image")
@admin_required
def richmenu_image(richmenu_id):
    menu, err = _menu_or_404(richmenu_id)
    if err:
        return err
    if not menu.get("imageExt"):
        return _err("這個 Rich Menu 還沒有圖片", 404)
    return send_from_directory(c().RICHMENU_DIR, f"{richmenu_id}.{menu['imageExt']}")


@bp.post("/api/richmenus/<richmenu_id>/default")
@admin_required
def richmenu_set_default(richmenu_id):
    menu, err = _menu_or_404(richmenu_id)
    if err:
        return err
    if not menu.get("imageExt"):
        return _err("請先上傳圖片，才能設為預設")
    c().db.set_setting(_default_key(menu["botId"]), richmenu_id)
    c().notify_richmenu_changed(menu["botId"])
    _audit("richmenu.default", bot=menu["botId"], id=richmenu_id)
    return jsonify({"ok": True})


@bp.delete("/api/richmenu-default")
@admin_required
def richmenu_clear_default():
    bot, err = _bot_or_404(request.args.get("botId"))
    if err:
        return err
    c().db.set_setting(_default_key(bot["bot_id"]), None)
    c().notify_richmenu_changed(bot["bot_id"])
    _audit("richmenu.default.clear", bot=bot["bot_id"])
    return jsonify({"ok": True})


@bp.delete("/api/richmenus/<richmenu_id>")
@admin_required
def richmenu_delete(richmenu_id):
    menu, err = _menu_or_404(richmenu_id)
    if err:
        return err
    bot_id = menu["botId"]
    was_default = c().db.get_setting(_default_key(bot_id)) == richmenu_id
    affected = c().db.users_with_richmenu(bot_id, richmenu_id)
    _remove_menu_image(menu)
    c().db.delete_richmenu(bot_id, richmenu_id)
    c().notify_richmenu_changed(bot_id, None if was_default else affected)
    _audit("richmenu.delete", bot=bot_id, id=richmenu_id)
    return jsonify({"ok": True})


@bp.post("/api/users/<user_id>/richmenu")
@admin_required
def user_richmenu_link(user_id):
    data = _json()
    user, err = _get_user_or_404(user_id)
    if err:
        return err
    bot, err = _bot_or_404(data.get("botId"))
    if err:
        return err
    if c().db.get_membership(bot["bot_id"], user_id) is None:
        return _err("這位使用者不是該 Bot 的好友", 404)
    menu, err = _menu_or_404(data.get("richMenuId"))
    if err:
        return err
    if menu["botId"] != bot["bot_id"]:
        return _err("這個 Rich Menu 不屬於該 Bot", 400)
    if not menu.get("imageExt"):
        return _err("請先上傳圖片，才能綁定給使用者")
    c().db.link_richmenu(bot["bot_id"], user_id, menu["richMenuId"])
    c().notify_richmenu_changed(bot["bot_id"], [user_id])
    _audit("richmenu.link", bot=bot["bot_id"], user=user_id, id=menu["richMenuId"])
    return jsonify({"ok": True})


@bp.delete("/api/users/<user_id>/richmenu")
@admin_required
def user_richmenu_unlink(user_id):
    user, err = _get_user_or_404(user_id)
    if err:
        return err
    bot, err = _bot_or_404(request.args.get("botId"))
    if err:
        return err
    c().db.unlink_richmenu(bot["bot_id"], user_id)
    c().notify_richmenu_changed(bot["bot_id"], [user_id])
    _audit("richmenu.unlink", bot=bot["bot_id"], user=user_id)
    return jsonify({"ok": True})


@bp.post("/api/richmenu-aliases")
@admin_required
def alias_set():
    data = _json()
    bot, err = _bot_or_404(data.get("botId"))
    if err:
        return err
    alias_id = data.get("aliasId")
    if not isinstance(alias_id, str) or not c().is_safe_id(alias_id) or len(alias_id) > 32:
        return _err("別名只能用英數字、底線、連字號、點，最長 32 字")
    menu, err = _menu_or_404(data.get("richMenuId"))
    if err:
        return err
    if menu["botId"] != bot["bot_id"]:
        return _err("這個 Rich Menu 不屬於該 Bot", 400)
    c().db.set_richmenu_alias(bot["bot_id"], alias_id, menu["richMenuId"])
    _audit("richmenu.alias.set", bot=bot["bot_id"], alias=alias_id, id=menu["richMenuId"])
    return jsonify({"ok": True})


@bp.delete("/api/richmenu-aliases/<alias_id>")
@admin_required
def alias_delete(alias_id):
    bot, err = _bot_or_404(request.args.get("botId"))
    if err:
        return err
    if not c().is_safe_id(alias_id) or not c().db.delete_richmenu_alias(bot["bot_id"], alias_id):
        return _err("找不到這個別名", 404)
    _audit("richmenu.alias.delete", bot=bot["bot_id"], alias=alias_id)
    return jsonify({"ok": True})


# ============================================================================
# 伺服器設定與管理員密碼（Bot 的金鑰、Webhook 在 admin_bots.py）
# ============================================================================
@bp.get("/api/settings")
@admin_required
def settings_get():
    ctx = c()
    return jsonify({
        "serverUrl": ctx.SERVER_URL,
        "port": cfg.PORT,
        "debug": ctx.DEBUG,
        "corsOrigins": cfg.CORS_ALLOWED_ORIGINS,
        "maxUploadMb": ctx.MAX_UPLOAD_MB,
        "adminSessionHours": cfg.ADMIN_SESSION_HOURS,
        "adminPasswordSource": cfg.SECRET_SOURCES.get("ADMIN_PASSWORD", "file"),
        "logRetentionDays": cfg.LOG_RETENTION_DAYS,
        "webhookRetryDelays": cfg.WEBHOOK_RETRY_DELAYS,
        "scheduleGraceMinutes": cfg.SCHEDULE_GRACE_MINUTES,
    })


@bp.post("/api/password")
@admin_required
def password_change():
    data = _json()
    ok, wait = _verify_with_limit(data.get("current"))
    if wait:
        return _too_many(wait)
    if not ok:
        return _err("目前的密碼不正確", 403)
    new = data.get("new")
    if not isinstance(new, str) or not (10 <= len(new) <= 128):
        return _err("新密碼長度需為 10～128 個字元")
    if cfg.SECRET_SOURCES.get("ADMIN_PASSWORD") == "env":
        return _err("管理員密碼由環境變數 LOCALBOT_ADMIN_PASSWORD 設定，請改環境變數後重啟", 409)
    cfg.save_secret("ADMIN_PASSWORD", new)
    session["pw"] = _pw_tag()  # 這個 session 維持登入，其他裝置全部登出
    _audit("password.change")
    return jsonify({"ok": True})


# ============================================================================
# 掛載
# ============================================================================
def init_admin(flask_app, ctx):
    """由 app.py 呼叫：ctx 是 app 模組本身。"""
    _State.ctx = ctx
    if "admin" in flask_app.blueprints:
        return
    flask_app.config.update(
        SESSION_COOKIE_NAME="localbot_admin",
        SESSION_COOKIE_PATH="/admin",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=ctx.SERVER_URL.lower().startswith("https://"),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=cfg.ADMIN_SESSION_HOURS),
    )
    import admin_automation  # noqa: F401 - 註冊排程推播 / Webhook 日誌的路由到 bp
    import admin_bots  # noqa: F401 - 註冊 Bot / 邀請碼的路由到 bp
    flask_app.register_blueprint(bp)
    logger.info("管理後台已啟用：/admin")
