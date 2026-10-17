"""管理後台：Bot、Bot 金鑰、Webhook 測試、邀請碼（掛在 admin_panel 的 blueprint 上）。"""
import json
import os
import secrets
import time
from urllib.parse import quote, urlparse

from flask import jsonify, request

from admin_panel import (_audit, _bot_or_404, _err, _json, _too_many, _verify_with_limit, admin_required, bp, c)
from localbot.utils import calculate_signature

MAX_NAME_LEN = 60
MAX_DESC_LEN = 200
SECRET_NAMES = {"CHANNEL_SECRET": "channel_secret", "CHANNEL_ACCESS_TOKEN": "channel_access_token"}
MAX_INVITE_USES = 1000
MAX_INVITE_HOURS = 24 * 365
DEFAULT_INVITE_HOURS = 24 * 7


def _check_url(value):
    if not isinstance(value, str) or not value.strip():
        return None, "請輸入 Webhook URL"
    value = value.strip()
    if len(value) > 500:
        return None, "Webhook URL 太長"
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None, "Webhook URL 必須是 http:// 或 https:// 開頭的完整網址"
    return value, None


def _check_name(value):
    if not isinstance(value, str) or not value.strip():
        return None, "請輸入 Bot 名稱"
    value = value.strip()
    if len(value) > MAX_NAME_LEN:
        return None, f"名稱最多 {MAX_NAME_LEN} 字"
    return value, None


def _check_desc(value):
    if value is None:
        return "", None
    if not isinstance(value, str) or len(value.strip()) > MAX_DESC_LEN:
        return None, f"說明最多 {MAX_DESC_LEN} 字"
    return value.strip(), None


def _bot_view(bot: dict, counts: dict, invites: dict, online: set = None) -> dict:
    n = counts.get(bot["bot_id"], {})
    return {
        "botId": bot["bot_id"], "name": bot["name"], "description": bot.get("description") or "",
        "webhookUrl": bot["webhook_url"], "enabled": bot["enabled"],
        "createdAt": bot["created_at"], "updatedAt": bot["updated_at"],
        "memberCount": n.get("members", 0), "blockedCount": n.get("blocked", 0),
        "activeInvites": invites.get(bot["bot_id"], 0),
        "tokenHint": f"…{bot['channel_access_token'][-4:]}",
        "avatarUrl": c().bot_avatar_path(bot),
    }


def _invite_status(inv: dict, now: int) -> str:
    if inv["revoked"]:
        return "revoked"
    if inv["expires_at"] is not None and inv["expires_at"] <= now:
        return "expired"
    if inv["uses"] >= inv["max_uses"]:
        return "used_up"
    return "active"


def invite_link(code: str) -> str:
    return f"localbot://join?server={quote(c().SERVER_URL.rstrip('/'), safe='')}&code={code}"


def _invite_view(inv: dict, names: dict, now: int) -> dict:
    code = inv["code"]
    return {
        "code": code, "display": c().format_invite_code(code), "botId": inv["bot_id"],
        "botName": names.get(inv["bot_id"]), "label": inv.get("label") or "",
        "maxUses": inv["max_uses"], "uses": inv["uses"], "expiresAt": inv["expires_at"],
        "revoked": inv["revoked"], "status": _invite_status(inv, now), "createdAt": inv["created_at"],
        "link": invite_link(code),
    }


def _active_invite_counts() -> dict:
    now = int(time.time() * 1000)
    out = {}
    for inv in c().db.list_invites():
        if _invite_status(inv, now) == "active":
            out[inv["bot_id"]] = out.get(inv["bot_id"], 0) + 1
    return out


def _view_one(bot_id: str) -> dict:
    db = c().db
    return _bot_view(db.get_bot(bot_id), db.bot_member_counts(), _active_invite_counts())


# ============================================================================
# Bot
# ============================================================================
@bp.get("/api/bots")
@admin_required
def bots_list():
    db = c().db
    counts, invites = db.bot_member_counts(), _active_invite_counts()
    return jsonify({"bots": [_bot_view(b, counts, invites) for b in db.list_bots()],
                    "serverUrl": c().SERVER_URL})


@bp.post("/api/bots")
@admin_required
def bot_create():
    data = _json()
    name, msg = _check_name(data.get("name"))
    if msg:
        return _err(msg)
    desc, msg = _check_desc(data.get("description"))
    if msg:
        return _err(msg)
    url, msg = _check_url(data.get("webhookUrl"))
    if msg:
        return _err(msg)
    bot_id = data.get("botId")
    if bot_id in (None, ""):
        bot_id = f"bot-{secrets.token_hex(4)}"
    elif not isinstance(bot_id, str) or not c().is_safe_id(bot_id) or len(bot_id) > 32:
        return _err("Bot ID 只能用英數字、底線、連字號、點，最長 32 字")
    if c().db.get_bot(bot_id):
        return _err("這個 Bot ID 已經存在", 409)
    channel_secret = secrets.token_urlsafe(32)
    token = secrets.token_urlsafe(32)
    c().db.create_bot(bot_id, name, desc, channel_secret, token, url, True)
    _audit("bot.create", bot=bot_id)
    view = _view_one(bot_id)
    view["channelSecret"] = channel_secret          # 建立當下順便顯示一次，之後要輸入密碼才能查看
    view["channelAccessToken"] = token
    return jsonify(view), 201


@bp.get("/api/bots/<bot_id>")
@admin_required
def bot_get(bot_id):
    bot, err = _bot_or_404(bot_id)
    return err or jsonify(_view_one(bot["bot_id"]))


@bp.patch("/api/bots/<bot_id>")
@admin_required
def bot_update(bot_id):
    bot, err = _bot_or_404(bot_id)
    if err:
        return err
    data = _json()
    fields = {}
    if "name" in data:
        fields["name"], msg = _check_name(data["name"])
        if msg:
            return _err(msg)
    if "description" in data:
        fields["description"], msg = _check_desc(data["description"])
        if msg:
            return _err(msg)
    if "webhookUrl" in data:
        fields["webhook_url"], msg = _check_url(data["webhookUrl"])
        if msg:
            return _err(msg)
    if "enabled" in data:
        if not isinstance(data["enabled"], bool):
            return _err("enabled 必須是 true / false")
        fields["enabled"] = data["enabled"]
    if not fields:
        return _err("沒有要修改的欄位")
    c().db.update_bot(bot["bot_id"], **fields)
    _audit("bot.update", bot=bot["bot_id"], fields=",".join(sorted(fields)))
    return jsonify(_view_one(bot["bot_id"]))


@bp.delete("/api/bots/<bot_id>")
@admin_required
def bot_delete(bot_id):
    bot, err = _bot_or_404(bot_id)
    if err:
        return err
    data = _json()
    ok, wait = _verify_with_limit(data.get("password"))
    if wait:
        return _too_many(wait)
    if not ok:
        return _err("密碼錯誤", 403)
    if data.get("confirm") is not True:
        return _err("刪除 Bot 需要 confirm: true")
    members = c().db.list_user_ids(bot["bot_id"], include_blocked=True)
    _remove_avatar_file(bot.get("avatar"))
    menus = c().db.delete_bot(bot["bot_id"])
    for m in menus:
        if m.get("imageExt"):
            try:
                os.remove(os.path.join(c().RICHMENU_DIR, f"{m['richMenuId']}.{m['imageExt']}"))
            except OSError:
                pass
    _audit("bot.delete", bot=bot["bot_id"], members=len(members), menus=len(menus))
    return jsonify({"deleted": True, "members": len(members)})


# ============================================================================
# Bot 頭像（App 的 Bot 清單、聊天室會顯示）
# ============================================================================
def _remove_avatar_file(name):
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return
    try:
        os.remove(os.path.join(c().AVATAR_DIR, name))
    except OSError:
        pass


@bp.post("/api/bots/<bot_id>/avatar")
@admin_required
def bot_avatar_upload(bot_id):
    """請求本文就是圖片（PNG / JPEG / WebP，1 MB 以內）。"""
    bot, err = _bot_or_404(bot_id)
    if err:
        return err
    data = request.get_data(cache=False) or b""
    if not data:
        return _err("請選擇圖片")
    if len(data) > c().AVATAR_MAX_BYTES:
        return _err("圖片需在 1 MB 以內", 413)
    ext = c()._detect_image(data, allow_webp=True)
    if ext is None:
        return _err("圖片必須是 PNG、JPEG 或 WebP")
    name = f"{bot['bot_id']}-{secrets.token_hex(4)}.{ext}"
    with open(os.path.join(c().AVATAR_DIR, name), "wb") as f:
        f.write(data)
    old = bot.get("avatar")
    c().db.update_bot(bot["bot_id"], avatar=name)
    _remove_avatar_file(old)
    _audit("bot.avatar.upload", bot=bot["bot_id"], bytes=len(data))
    return jsonify(_view_one(bot["bot_id"]))


@bp.delete("/api/bots/<bot_id>/avatar")
@admin_required
def bot_avatar_delete(bot_id):
    bot, err = _bot_or_404(bot_id)
    if err:
        return err
    if bot.get("avatar"):
        c().db.update_bot(bot["bot_id"], avatar=None)
        _remove_avatar_file(bot["avatar"])
        _audit("bot.avatar.delete", bot=bot["bot_id"])
    return jsonify(_view_one(bot["bot_id"]))


# ============================================================================
# Bot 金鑰（顯示 / 重新產生都要再輸入一次管理員密碼）
# ============================================================================
def _secret_field(name):
    field = SECRET_NAMES.get(name)
    return (field, None) if field else (None, _err("未知的金鑰名稱", 404))


@bp.post("/api/bots/<bot_id>/secrets/<name>/reveal")
@admin_required
def bot_secret_reveal(bot_id, name):
    bot, err = _bot_or_404(bot_id)
    if err:
        return err
    field, err = _secret_field(name)
    if err:
        return err
    ok, wait = _verify_with_limit(_json().get("password"))
    if wait:
        return _too_many(wait)
    if not ok:
        return _err("密碼錯誤", 403)
    _audit("bot.secret.reveal", bot=bot["bot_id"], name=name)
    return jsonify({"name": name, "value": bot[field]})


@bp.post("/api/bots/<bot_id>/secrets/<name>/regenerate")
@admin_required
def bot_secret_regenerate(bot_id, name):
    bot, err = _bot_or_404(bot_id)
    if err:
        return err
    field, err = _secret_field(name)
    if err:
        return err
    data = _json()
    ok, wait = _verify_with_limit(data.get("password"))
    if wait:
        return _too_many(wait)
    if not ok:
        return _err("密碼錯誤", 403)
    if data.get("confirm") is not True:
        return _err("需要 confirm: true")
    value = secrets.token_urlsafe(32)
    c().db.update_bot(bot["bot_id"], **{field: value})
    _audit("bot.secret.regenerate", bot=bot["bot_id"], name=name)
    return jsonify({"name": name, "value": value})


# ============================================================================
# Webhook 測試（等同 LINE Developers 的 Verify 按鈕）
# ============================================================================
@bp.post("/api/bots/<bot_id>/webhook/test")
@admin_required
def bot_webhook_test(bot_id):
    bot, err = _bot_or_404(bot_id)
    if err:
        return err
    body = json.dumps({"destination": bot["bot_id"], "events": []})
    signature = calculate_signature(bot["channel_secret"], body)
    started = time.time()
    result = {"url": bot["webhook_url"]}
    try:
        res = c().http_requests.post(
            bot["webhook_url"], data=body, timeout=5,
            headers={"Content-Type": "application/json",
                     "X-Line-Signature": signature, "X-LocalBot-Signature": signature})
        result.update(ok=res.status_code < 400, status=res.status_code)
    except Exception as e:  # noqa: BLE001 - 只回報類型與簡短訊息
        result.update(ok=False, status=None, error=f"{type(e).__name__}: {str(e)[:160]}")
    result["ms"] = int((time.time() - started) * 1000)
    return jsonify(result)


# ============================================================================
# 邀請碼
# ============================================================================
@bp.get("/api/invites")
@admin_required
def invites_list():
    bot_id = request.args.get("botId") or None
    if bot_id and (not c().is_safe_id(bot_id) or c().db.get_bot(bot_id) is None):
        return _err("找不到這個 Bot", 404)
    now = int(time.time() * 1000)
    names = {b["bot_id"]: b["name"] for b in c().db.list_bots()}
    return jsonify({"invites": [_invite_view(i, names, now) for i in c().db.list_invites(bot_id)]})


@bp.post("/api/invites")
@admin_required
def invite_create():
    data = _json()
    bot, err = _bot_or_404(data.get("botId"))
    if err:
        return err
    label = data.get("label")
    if label is not None and (not isinstance(label, str) or len(label.strip()) > MAX_NAME_LEN):
        return _err(f"備註最多 {MAX_NAME_LEN} 字")
    label = (label or "").strip() or None
    max_uses = data.get("maxUses", 1)
    if isinstance(max_uses, bool) or not isinstance(max_uses, int) or not 1 <= max_uses <= MAX_INVITE_USES:
        return _err(f"可使用次數需為 1～{MAX_INVITE_USES}")
    hours = data.get("expiresInHours", DEFAULT_INVITE_HOURS)
    expires_at = None
    if hours is not None:
        if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 0 < hours <= MAX_INVITE_HOURS:
            return _err(f"有效時間需為 1 小時～{MAX_INVITE_HOURS} 小時，或不限期")
        expires_at = int(time.time() * 1000 + hours * 3600_000)
    code = None
    for _ in range(5):
        candidate = c().new_invite_code()
        if c().db.get_invite(candidate) is None:
            code = candidate
            break
    if code is None:
        return _err("無法產生邀請碼，請再試一次", 500)
    c().db.create_invite(code, bot["bot_id"], label, max_uses, expires_at)
    _audit("invite.create", bot=bot["bot_id"], max_uses=max_uses, expires=expires_at)
    now = int(time.time() * 1000)
    return jsonify(_invite_view(c().db.get_invite(code), {bot["bot_id"]: bot["name"]}, now)), 201


def _invite_or_404(code):
    code = c().normalize_invite_code(code)
    inv = c().db.get_invite(code) if code else None
    if inv is None:
        return None, _err("找不到這組邀請碼", 404)
    return inv, None


@bp.post("/api/invites/<code>/revoke")
@admin_required
def invite_revoke(code):
    inv, err = _invite_or_404(code)
    if err:
        return err
    c().db.revoke_invite(inv["code"])
    _audit("invite.revoke", bot=inv["bot_id"])
    return jsonify({"ok": True})


@bp.delete("/api/invites/<code>")
@admin_required
def invite_delete(code):
    inv, err = _invite_or_404(code)
    if err:
        return err
    c().db.delete_invite(inv["code"])
    _audit("invite.delete", bot=inv["bot_id"])
    return jsonify({"deleted": True})
