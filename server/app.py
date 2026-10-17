"""
LocalBot Platform Server (LINE Platform Emulator).

角色：模擬 LINE 平台
- 手機 Flutter App 發訊息到這裡
- 這裡用 HMAC 簽名後，把 Webhook 事件 POST 轉發到你的 Bot 程式
- 你的 Bot 程式呼叫 line_bot_api.reply_message() / push_message() 時，
  實際上是 HTTP POST 回到這裡的 /api/v1/bot/reply 或 /api/v1/bot/push
- 這裡再透過 Socket.IO 即時推送給手機 App

架構圖：
  Flutter App ──POST /callback──► app.py ──POST /callback──► 你的 Bot (localhost:8000)
                                                                    │
  Flutter App ◄──Socket.IO────── app.py ◄──POST /api/reply─────────┘
"""
import os
import re
import hmac
import html
import hashlib
import secrets
import uuid
import time
import json
import logging
import sys
import threading
import requests as http_requests
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, abort, g
from flask_socketio import SocketIO, emit, join_room, leave_room

from localconfig import (
    SERVER_URL, HOST, PORT, CHANNEL_ACCESS_TOKEN, CHANNEL_SECRET,
    FLASK_SECRET_KEY, DEBUG, CORS_ALLOWED_ORIGINS, MAX_UPLOAD_MB,
    ALLOWED_UPLOAD_EXTENSIONS, DOWNLOAD_ONLY_EXTENSIONS, DATABASE_PATH, MEDIA_DIR, STICKER_DIR,
    IMAGEMAP_DIR, RICHMENU_DIR, RICHMENU_MAX_IMAGE_BYTES, BOT_WEBHOOK_URL, ADMIN_ENABLED,
    AVATAR_DIR, AVATAR_MAX_BYTES,
    WEBHOOK_TIMEOUT, WORKERS_ENABLED
)
from database import Database, DEFAULT_BOT_ID
import webhook_delivery
import scheduled_push
from localbot.utils import calculate_signature

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LocalBotPlatform")

# Initialize Flask & Socket.IO
app = Flask(__name__, static_folder=None)
app.config['SECRET_KEY'] = FLASK_SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins=CORS_ALLOWED_ORIGINS, async_mode="threading")

# Initialize DB
db = Database(DATABASE_PATH)

# Connected clients map: user_id -> set of sid
connected_users = {}

# 允許的 ID 格式（避免路徑穿越 / 注入）
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def is_safe_id(value) -> bool:
    return isinstance(value, str) and bool(SAFE_ID_RE.match(value)) and ".." not in value


# ============================================================================
# Auth helpers
# ============================================================================
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_user_token() -> str:
    """發給每位使用者／裝置自己的金鑰（伺服器只存 SHA-256，無法還原）。"""
    return "lbu_" + secrets.token_urlsafe(32)


def _safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def verify_user_token(user_id, token) -> bool:
    """驗證使用者金鑰。已被撤銷或從未發過金鑰（token_hash 為空）一律失敗。"""
    if not isinstance(user_id, str) or not user_id or not isinstance(token, str) or not token:
        return False
    stored = db.get_token_hash(user_id)
    return bool(stored) and _safe_equal(stored, hash_token(token))


def find_bot_by_access_token(token: str):
    if not token:
        return None
    for bot in db.list_bots():
        if _safe_equal(bot["channel_access_token"], token):
            return bot
    return None


def require_bot_token(func):
    """Bot → 平台 API 必須帶 Authorization: Bearer <這個 Bot 的 CHANNEL_ACCESS_TOKEN>。

    驗證成功後，g.bot 是呼叫的 Bot；之後所有資料操作都限定在這個 Bot 的範圍內。
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        bot = find_bot_by_access_token(token)
        if bot is None or not bot["enabled"]:
            return jsonify({"status": "error", "message": "invalid access token"}), 401
        g.bot = bot
        return func(*args, **kwargs)
    return wrapper


def bot_id() -> str:
    return g.bot["bot_id"]


def ensure_default_bot():
    """第一次啟動（資料庫還沒有任何 Bot）時，用 .env／金鑰檔的設定建立「預設 Bot」，舊版升級後原本的 Bot 程式不用改設定。"""
    if db.get_setting("default_bot_seeded"):
        return
    if not db.list_bots():
        db.create_bot(DEFAULT_BOT_ID, "預設 Bot", "第一次啟動時自動建立", CHANNEL_SECRET, CHANNEL_ACCESS_TOKEN,
                      BOT_WEBHOOK_URL)
        logger.info("已建立預設 Bot（bot_id=default）")
    db.set_setting("default_bot_seeded", "1")


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    return resp


# ============================================================================
# Helper: Push messages to Flutter App via Socket.IO (or offline queue)
# ============================================================================
def deliver_to_client(bot_id: str, user_id: str, messages: list) -> list:
    """Bot（bot_id）傳訊息給它的好友 user_id（在線：Socket.IO，離線：進佇列）。

    回傳每則訊息的 messageId（供 LINE 相容 API 回應 sentMessages 使用）。
    不是好友或已封鎖時訊息會被丟棄（與 LINE 相同，Bot 不會收到錯誤）。
    """
    sent_ids = []
    membership = db.get_membership(bot_id, user_id)
    if membership is None or membership["blocked"]:
        reason = "is not a friend of" if membership is None else "has blocked"
        logger.info(f"User {user_id} {reason} bot {bot_id}, {len(messages)} message(s) dropped")
        return [f"bot_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}" for _ in messages]
    for msg in messages:
        msg_id = f"bot_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        msg_data = {
            "messageId": msg_id,
            "botId": bot_id,
            "userId": user_id,
            "direction": "outgoing",
            "messageType": msg.get("type", "text"),
            "content": msg,
            "createdAt": int(time.time() * 1000)
        }

        db.save_message(
            bot_id=bot_id,
            message_id=msg_id,
            user_id=user_id,
            direction="outgoing",
            message_type=msg.get("type", "text"),
            content=msg
        )

        if user_id in connected_users and connected_users[user_id]:
            socketio.emit("bot_message", msg_data, room=user_id)
            logger.info(f"Delivered message {msg_id} via Socket.IO to {user_id} (bot {bot_id})")
        else:
            db.enqueue_offline_message(bot_id, user_id, msg_data)
            logger.info(f"User {user_id} offline, enqueued message {msg_id} (bot {bot_id})")
        sent_ids.append(msg_id)
    return sent_ids


# LINE Messaging API 的限制：每次最多 5 則訊息、Quick Reply 最多 13 個按鈕
MAX_MESSAGES_PER_REQUEST = 5
MAX_QUICK_REPLY_ITEMS = 13
MAX_MULTICAST_TARGETS = 500


def validate_messages(messages):
    """檢查 Bot 送來的訊息陣列，回傳錯誤訊息字串；沒問題回傳 None。"""
    if not isinstance(messages, list) or not messages:
        return "messages must be a non-empty array"
    if len(messages) > MAX_MESSAGES_PER_REQUEST:
        return f"messages must not exceed {MAX_MESSAGES_PER_REQUEST} items"
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
            return f"messages[{i}] must be an object with a 'type'"
        qr = msg.get("quickReply")
        if qr is not None:
            items = qr.get("items") if isinstance(qr, dict) else None
            if not isinstance(items, list) or not items:
                return f"messages[{i}].quickReply.items must be a non-empty array"
            if len(items) > MAX_QUICK_REPLY_ITEMS:
                return f"messages[{i}].quickReply.items must not exceed {MAX_QUICK_REPLY_ITEMS} items"
            for j, item in enumerate(items):
                action = item.get("action") if isinstance(item, dict) else None
                if not isinstance(action, dict) or not isinstance(action.get("type"), str):
                    return f"messages[{i}].quickReply.items[{j}].action is invalid"
    return None


def line_error(message: str, status: int = 400):
    """LINE 風格的錯誤回應：{"message": "..."}。"""
    return jsonify({"message": message}), status


def forward_to_bot(bot: dict, body: str, signature: str):
    """Forward webhook event to the Bot's webhook (like LINE Platform does).

    只負責「送一次」。失敗原因留在 webhook_delivery.forward_state，由 webhook_delivery 決定要不要重試。
    """
    state = webhook_delivery.forward_state
    state.error = None
    state.snippet = None
    url = bot["webhook_url"]
    try:
        res = http_requests.post(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Line-Signature": signature,
                "X-LocalBot-Signature": signature,
            },
            timeout=WEBHOOK_TIMEOUT,
        )
        logger.info(f"Forwarded webhook to {url} (bot {bot['bot_id']}), status={res.status_code}")
        if res.status_code >= 400:
            state.snippet = " ".join((res.text or "").split())[:200]
        return res.status_code
    except Exception as e:
        logger.error(f"Failed to forward webhook to {url} (bot {bot['bot_id']}): {e}")
        state.error = f"{type(e).__name__}: {str(e)[:200]}"
        return 500


def run_in_background(func, *args):
    """在背景執行（測試時可替換成同步執行）。"""
    threading.Thread(target=func, args=args, daemon=True).start()


class SerialQueues:
    """同一個 key（Bot + 使用者）的工作依送出順序一個接一個在背景執行。

    App 連續送出好幾則訊息時，Bot 收到的順序要和使用者送出的順序相同；
    不同使用者 / 不同 Bot 之間互不等待。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._queues = {}

    def submit(self, key, func, *args):
        with self._lock:
            queue = self._queues.get(key)
            start = queue is None
            if start:
                queue = self._queues[key] = []
            queue.append((func, args))
        if start:
            run_in_background(self._drain, key)

    def _drain(self, key):
        while True:
            with self._lock:
                queue = self._queues.get(key)
                if not queue:
                    self._queues.pop(key, None)
                    return
                func, args = queue.pop(0)
            try:
                func(*args)
            except Exception:  # noqa: BLE001
                logger.exception("背景工作失敗")

    def pending(self) -> int:
        with self._lock:
            return sum(len(q) for q in self._queues.values())


app_deliveries = SerialQueues()


def deliver_for_app(bot_id_value: str, user_id: str, body: str, message_ids: list):
    """App 的「快速送出」：在背景轉送給 Bot；最後確定送不到時用 Socket.IO 通知 App 標示「無法傳送」。

    可重試的失敗（Bot 沒開、5xx…）會由背景工作自動重送，不通知 App（與同步模式回 200 + queued 相同）。
    """
    try:
        result = webhook_delivery.deliver(bot_id_value, body)
    except Exception:  # noqa: BLE001
        logger.exception("快速送出：轉送失敗")
        result = {"ok": False, "state": "dead", "error": "內部錯誤"}
    if result.get("ok") or result.get("state") == "retrying":
        return
    reason = result.get("error") or f"Bot returned {result.get('status') or 'error'}"
    notify_delivery_failed(bot_id_value, user_id, message_ids, reason)


def notify_delivery_failed(bot_id_value: str, user_id: str, message_ids: list, reason: str):
    payload = {"botId": bot_id_value, "messageIds": list(message_ids), "reason": str(reason)[:200]}
    if user_id in connected_users and connected_users[user_id]:
        socketio.emit("delivery_failed", payload, room=user_id)
    logger.warning(f"Delivery to bot {bot_id_value} failed for {user_id}: {payload['reason']}")


def send_platform_event(bot_id: str, user_id: str, event_type: str, **extra):
    """
    由平台自己產生事件並轉送給 Bot（例如 follow / unfollow），
    就像 LINE 平台在使用者加好友或封鎖時做的事。
    """
    event = {
        "type": event_type,
        "mode": "active",
        "timestamp": int(time.time() * 1000),
        "source": {"type": "user", "userId": user_id},
        "webhookEventId": uuid.uuid4().hex.upper(),
        "deliveryContext": {"isRedelivery": False},
    }
    if event_type in ("follow", "join", "memberJoined"):
        reply_token = f"reply_{uuid.uuid4().hex}"
        db.save_reply_token(bot_id, reply_token, user_id)
        event["replyToken"] = reply_token
    event.update(extra)
    body = json.dumps({"destination": bot_id, "events": [event]}, ensure_ascii=False)
    run_in_background(webhook_delivery.deliver_safe, bot_id, body)
    logger.info(f"Platform event '{event_type}' for {user_id} queued to bot {bot_id}")
    return event


# ============================================================================
# HTTP Endpoints: Flutter App → Platform
# ============================================================================

# ---- 加入 Bot（邀請碼）----
INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉容易看錯的 I、O、0、1
INVITE_CODE_LENGTH = 10
JOIN_WINDOW_SECONDS = 600
JOIN_FAIL_LIMIT_PER_IP = 10
JOIN_FAIL_LIMIT_GLOBAL = 100  # 放在 Cloudflare Tunnel / Nginx 後面時所有人的 IP 相同，所以另外限制整體
_join_lock = threading.Lock()
_join_fails = {}


def new_invite_code() -> str:
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def normalize_invite_code(value) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper() if isinstance(value, str) else ""


def format_invite_code(code: str) -> str:
    half = len(code) // 2
    return f"{code[:half]}-{code[half:]}"


def reset_join_limiter():
    with _join_lock:
        _join_fails.clear()


def _join_prune(key):
    cutoff = time.time() - JOIN_WINDOW_SECONDS
    fails = [t for t in _join_fails.get(key, []) if t > cutoff]
    _join_fails[key] = fails
    return fails


def _join_blocked(ip) -> bool:
    with _join_lock:
        return (len(_join_prune(ip)) >= JOIN_FAIL_LIMIT_PER_IP
                or len(_join_prune(None)) >= JOIN_FAIL_LIMIT_GLOBAL)


def _join_record_fail(ip):
    with _join_lock:
        _join_prune(ip).append(time.time())
        _join_prune(None).append(time.time())


def bot_avatar_path(bot: dict) -> str:
    """Bot 頭像的網址路徑（相對於伺服器網址）；沒有頭像時是空字串。檔名每次上傳都不同，App 可放心快取。"""
    name = bot.get("avatar")
    return f"/avatars/{name}" if name else ""


def bot_public(bot: dict) -> dict:
    """App 看得到的 Bot 資訊（絕不包含金鑰與 Webhook 位址）。"""
    return {"botId": bot["bot_id"], "name": bot["name"], "description": bot.get("description") or "",
            "avatarUrl": bot_avatar_path(bot)}


def _app_user_or_401(user_id):
    """App 端 API 共用：驗證 userId + X-LocalBot-Token。"""
    if not is_safe_id(user_id) or not verify_user_token(user_id, request.headers.get("X-LocalBot-Token")):
        abort(401, "Invalid user token")


def _app_bot_member_or_error(user_id, bot_id_value):
    """驗證 userId 是 bot 的好友。回傳 (bot, membership)；失敗時直接 abort。"""
    if not is_safe_id(bot_id_value):
        abort(400, "Invalid botId")
    bot = db.get_bot(bot_id_value)
    membership = db.get_membership(bot_id_value, user_id) if bot else None
    if bot is None or membership is None:
        abort(404, "Not a friend of this bot")
    return bot, membership


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "LocalBot Platform",
        "version": "3.1.0",
    })


@app.route("/join", methods=["POST"])
def join():
    """用邀請碼加入 Bot（成為它的好友）。

    - 全新的 userId：建立使用者並發給專屬金鑰（只在這次回應出現，伺服器只存雜湊）。
    - 已有金鑰的 userId：必須帶 X-LocalBot-Token，才能再加入另一個 Bot（不會重發金鑰）。
    - 金鑰已被撤銷、或從舊版升級而沒有金鑰的 userId：用邀請碼即可重新領取新金鑰（管理員發的邀請碼就是授權）。
    """
    data = request.get_json(force=True, silent=True) or {}
    ip = request.remote_addr or "?"
    if _join_blocked(ip):
        return jsonify({"status": "error", "message": "嘗試次數過多，請稍後再試"}), 429
    code = normalize_invite_code(data.get("code"))
    user_id = data.get("userId")
    if not is_safe_id(user_id):
        abort(400, "Invalid userId")
    display_name = str(data.get("displayName") or "User").strip()[:64] or "User"

    invite = db.get_invite(code) if code else None
    bot = db.get_bot(invite["bot_id"]) if invite else None
    if invite is None or bot is None or not bot["enabled"]:
        _join_record_fail(ip)
        return jsonify({"status": "error", "message": "邀請碼無效、已過期或已用完"}), 404

    user = db.get_user(user_id)
    issued_token = None
    if user is not None and user.get("token_hash"):
        if not verify_user_token(user_id, request.headers.get("X-LocalBot-Token")):
            _join_record_fail(ip)
            return jsonify({"status": "error", "message": "這個 userId 已經有金鑰，請帶上原本的金鑰"}), 401
    already_member = db.is_member(bot["bot_id"], user_id)

    if not already_member and not db.consume_invite(code):
        _join_record_fail(ip)
        return jsonify({"status": "error", "message": "邀請碼無效、已過期或已用完"}), 404
    try:
        if user is None:
            issued_token = new_user_token()
            db.create_user(user_id, display_name, hash_token(issued_token))
        elif not user.get("token_hash"):
            issued_token = new_user_token()
            db.set_user_token(user_id, hash_token(issued_token))
            db.update_display_name(user_id, display_name)
        else:
            db.update_display_name(user_id, display_name)
        is_new_member = db.add_membership(bot["bot_id"], user_id)
    except Exception:
        if not already_member:
            db.refund_invite(code)
        raise
    db.touch_user(user_id)
    logger.info(f"User {user_id} ({display_name}) joined bot {bot['bot_id']}"
                f"{' (new key issued)' if issued_token else ''}")
    if is_new_member:
        # 第一次加入：送 follow 事件給 Bot（Bot 可以回覆歡迎訊息）
        send_platform_event(bot["bot_id"], user_id, "follow", follow={"isUnblocked": False})

    resp = {"status": "success", "userId": user_id, "bot": bot_public(bot),
            "blocked": db.is_blocked(bot["bot_id"], user_id), "serverUrl": SERVER_URL}
    if issued_token:
        resp["token"] = issued_token
    return jsonify(resp)


@app.route("/me", methods=["GET"])
def me():
    """App 啟動時同步：我的資料與好友（Bot）清單。"""
    user_id = request.args.get("userId", "")
    _app_user_or_401(user_id)
    user = db.get_user(user_id)
    db.touch_user(user_id)
    bots = []
    for m in db.list_memberships(user_id):
        if m["name"] is None or not m["enabled"]:
            continue  # Bot 已被刪除或停用
        bots.append({"botId": m["bot_id"], "name": m["name"], "description": m["description"] or "",
                     "avatarUrl": bot_avatar_path(m),
                     "blocked": m["blocked"], "joinedAt": m["joined_at"], "lastMessageAt": m["last_message_at"]})
    return jsonify({"userId": user_id, "displayName": user.get("display_name") or "", "bots": bots})


@app.route("/profile", methods=["POST"])
def update_profile():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("userId", "")
    _app_user_or_401(user_id)
    name = data.get("displayName")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 64):
        abort(400, "Invalid displayName")
    db.update_display_name(user_id, name.strip())
    return jsonify({"status": "success"})


@app.route("/block", methods=["POST"])
def block():
    """使用者封鎖 / 解除封鎖某個 Bot，對應 LINE 的 unfollow / follow(isUnblocked) 事件。"""
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("userId")
    blocked = data.get("blocked")
    if not is_safe_id(user_id) or not isinstance(blocked, bool):
        abort(400, "Invalid request")
    _app_user_or_401(user_id)
    bot, membership = _app_bot_member_or_error(user_id, data.get("botId"))

    if membership["blocked"] != blocked:
        db.set_blocked(bot["bot_id"], user_id, blocked)
        if blocked:
            send_platform_event(bot["bot_id"], user_id, "unfollow")
        else:
            send_platform_event(bot["bot_id"], user_id, "follow", follow={"isUnblocked": True})
    return jsonify({"status": "success", "blocked": blocked})


@app.route("/leave", methods=["POST"])
def leave():
    """使用者刪除 Bot 好友：通知 Bot（unfollow），並清除這個 Bot 與使用者之間的所有資料。"""
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("userId")
    if not is_safe_id(user_id):
        abort(400, "Invalid request")
    _app_user_or_401(user_id)
    bot, membership = _app_bot_member_or_error(user_id, data.get("botId"))
    if not membership["blocked"]:
        send_platform_event(bot["bot_id"], user_id, "unfollow")
    db.remove_membership(bot["bot_id"], user_id)
    notify_richmenu_changed(bot["bot_id"], [user_id])
    logger.info(f"User {user_id} left bot {bot['bot_id']}")
    return jsonify({"status": "success"})


@app.route("/callback", methods=["POST"])
def callback():
    """
    Receive messages from Flutter App, then forward to the Bot's webhook.
    This is what LINE Platform does: receive from LINE App, forward to Bot webhook.

    App 以 X-LocalBot-Token（自己的金鑰）驗證身分；payload.destination 是要傳給哪個 Bot 的 bot_id。
    """
    body = request.get_data(as_text=True)
    if not body:
        abort(400, "Empty request body")

    try:
        payload = json.loads(body)
    except Exception:
        abort(400, "Malformed JSON")
    if not isinstance(payload, dict):
        abort(400, "Malformed JSON")
    events = payload.get("events", [])
    if not isinstance(events, list) or not events:
        abort(400, "Malformed events")

    # 所有事件必須來自同一位使用者，且該使用者金鑰有效
    user_ids = set()
    for ev in events:
        if not isinstance(ev, dict):
            abort(400, "Malformed events")
        source = ev.get("source", {}) or {}
        uid = source.get("userId") or source.get("user_id")
        if not is_safe_id(uid):
            abort(400, "Invalid userId")
        user_ids.add(uid)
    if len(user_ids) != 1:
        abort(400, "Events must come from a single user")
    user_id = user_ids.pop()
    if not verify_user_token(user_id, request.headers.get("X-LocalBot-Token")):
        logger.warning("Rejected /callback: invalid user token")
        abort(401, "Invalid user token")
    target_bot_id = payload.get("destination")
    if not is_safe_id(target_bot_id):
        abort(400, "Missing destination (bot id)")
    bot = db.get_bot(target_bot_id)
    if bot is None or not bot["enabled"]:
        abort(404, "Unknown bot")
    membership = db.get_membership(target_bot_id, user_id)
    if membership is None:
        abort(403, "Not a friend of this bot")
    if membership["blocked"]:
        abort(403, "User has blocked the bot")

    # Save reply_tokens and incoming messages to DB
    for ev in events:
        reply_token = ev.get("replyToken") or ev.get("reply_token")
        if reply_token:
            db.save_reply_token(target_bot_id, reply_token, user_id)

        if ev.get("type") == "message":
            msg = ev.get("message", {})
            msg_id = str(msg.get("id", uuid.uuid4().hex))
            db.save_message(
                bot_id=target_bot_id,
                message_id=msg_id,
                user_id=user_id,
                direction="incoming",
                message_type=msg.get("type", "text"),
                content=msg
            )
        elif ev.get("type") == "postback":
            pb = ev.get("postback", {})
            db.save_message(
                bot_id=target_bot_id,
                message_id=f"pb_{int(time.time()*1000)}",
                user_id=user_id,
                direction="incoming",
                message_type="postback",
                content=pb
            )

    # 快速送出（App 1.4 起帶 X-LocalBot-Async: 1）：訊息已存檔就先回 App，轉送給 Bot 在背景依序進行，
    # 最後確定送不到時用 Socket.IO 事件 delivery_failed 通知 App。舊版 App 不帶這個標頭，維持同步行為。
    if request.headers.get("X-LocalBot-Async") == "1":
        message_ids = [
            str(ev["message"]["id"]) for ev in events
            if ev.get("type") == "message" and isinstance(ev.get("message"), dict) and ev["message"].get("id")
        ]
        app_deliveries.submit((target_bot_id, user_id), deliver_for_app, target_bot_id, user_id, body, message_ids)
        resp = app.response_class("OK", status=200)
        resp.headers["X-LocalBot-Delivery"] = "async"
        return resp

    # 簽名後轉送給 Bot（和 LINE 平台一樣）。每次轉送都會留下紀錄，可重試的失敗會排入重試佇列。
    result = webhook_delivery.deliver(target_bot_id, body)
    if result.get("ok"):
        return "OK", 200
    if result.get("state") == "retrying":
        # 訊息已收下，平台會在背景重送給 Bot；App 不需要重傳
        resp = app.response_class("OK", status=200)
        resp.headers["X-LocalBot-Delivery"] = "queued"
        return resp
    return jsonify({"status": "error", "message": f"Bot returned {result.get('status') or 'error'}"}), 502


@app.route("/upload", methods=["POST"])
def upload():
    """Upload media file (image, audio, video)."""
    if 'file' not in request.files:
        abort(400, "No file provided")

    file = request.files['file']
    message_id = request.form.get("messageId") or uuid.uuid4().hex
    user_id = request.form.get("userId", "")

    if not verify_user_token(user_id, request.headers.get("X-LocalBot-Token")):
        abort(401, "Invalid app token")
    # messageId 會變成檔名，必須嚴格檢查避免路徑穿越
    if not is_safe_id(message_id):
        abort(400, "Invalid messageId")
    if not file.filename:
        abort(400, "Empty filename")

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ""
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        abort(400, "File type not allowed")
    saved_filename = f"{message_id}.{ext}"
    saved_path = os.path.join(MEDIA_DIR, saved_filename)
    file.save(saved_path)

    file_url = f"{SERVER_URL.rstrip('/')}/media/{saved_filename}"
    logger.info(f"Saved media file: {saved_path} (URL: {file_url})")

    return jsonify({
        "status": "success",
        "messageId": message_id,
        "filename": saved_filename,
        "url": file_url
    })


@app.route("/media/<path:filename>", methods=["GET"])
def get_media(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    # 文件類檔案一律下載，不在瀏覽器內直接開啟
    return send_from_directory(MEDIA_DIR, filename, as_attachment=ext in DOWNLOAD_ONLY_EXTENSIONS)


# LINE 的 Imagemap 會依螢幕寬度請求 {baseUrl}/240、/300、/460、/700、/1040
IMAGEMAP_SIZES = (240, 300, 460, 700, 1040)
IMAGE_EXTS = ("png", "jpg", "jpeg", "webp")


def _demo_imagemap_png(width: int) -> bytes:
    """產生示範用的 Imagemap 圖片（左右兩塊色塊，2:1），不需要任何圖片套件。"""
    import struct
    import zlib
    height = width // 2
    left = bytes((0x4F, 0x46, 0xE5))   # 靛藍
    right = bytes((0x0E, 0xA5, 0x8E))  # 青綠
    gap = bytes((0xFF, 0xFF, 0xFF))
    half = width // 2
    row = b"\x00" + left * (half - 2) + gap * 4 + right * (width - half - 2)
    raw = row * height

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


@app.route("/imagemap/<name>/<int:size>", methods=["GET"])
def get_imagemap_image(name, size):
    """
    Imagemap 圖片：放一張圖到 media/imagemap/<name>/ 即可（檔名 1040.png 或任意圖片），
    各種寬度都會回傳同一張，由 App 自行縮放。name 為 demo 時回傳內建示範圖。
    """
    if not is_safe_id(name) or size not in IMAGEMAP_SIZES:
        abort(404)
    folder = os.path.join(IMAGEMAP_DIR, name)
    if os.path.isdir(folder):
        candidates = [f"{size}.{e}" for e in IMAGE_EXTS] + [f"1040.{e}" for e in IMAGE_EXTS]
        candidates += sorted(f for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXTS))
        for fname in candidates:
            if os.path.isfile(os.path.join(folder, fname)):
                return send_from_directory(folder, fname)
    if name == "demo":
        return _demo_imagemap_png(size), 200, {"Content-Type": "image/png"}
    abort(404)


AVATAR_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.(png|jpg|webp)$")


@app.route("/avatars/<name>", methods=["GET"])
def get_avatar(name):
    """Bot 頭像（公開，與 LINE 的頭像網址一樣不需要登入）。"""
    if not AVATAR_NAME_RE.match(name) or not os.path.isfile(os.path.join(AVATAR_DIR, name)):
        abort(404)
    return send_from_directory(AVATAR_DIR, name, max_age=30 * 24 * 3600)


@app.route("/stickers/<package_id>/<sticker_id>", methods=["GET"])
def get_sticker(package_id, sticker_id):
    """Serve sticker image."""
    if not is_safe_id(package_id) or not is_safe_id(sticker_id):
        abort(400, "Invalid sticker id")
    package_dir = os.path.join(STICKER_DIR, package_id)
    for ext in ["png", "jpg", "jpeg", "webp"]:
        fname = f"{sticker_id}.{ext}"
        fpath = os.path.join(package_dir, fname)
        if os.path.exists(fpath):
            return send_from_directory(package_dir, fname)

    safe_label = html.escape(sticker_id)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">
        <rect width="160" height="160" rx="30" fill="#f0fdf4" stroke="#22c55e" stroke-width="4"/>
        <text x="80" y="70" font-size="48" text-anchor="middle">😊</text>
        <text x="80" y="115" font-size="14" font-family="sans-serif" fill="#166534" text-anchor="middle">Sticker {safe_label}</text>
    </svg>'''
    return svg, 200, {'Content-Type': 'image/svg+xml'}


@app.route("/stickers/list", methods=["GET"])
def list_stickers():
    packages = []
    if os.path.exists(STICKER_DIR):
        for pkg in os.listdir(STICKER_DIR):
            pkg_path = os.path.join(STICKER_DIR, pkg)
            if os.path.isdir(pkg_path):
                stickers = [
                    os.path.splitext(f)[0]
                    for f in os.listdir(pkg_path)
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
                ]
                packages.append({"packageId": pkg, "stickers": stickers})

    if not packages:
        packages = [{"packageId": "1", "name": "Default Pack", "stickers": ["1", "2", "3", "4", "5"]}]

    return jsonify({"packages": packages})


@app.route("/history", methods=["GET"])
def get_history():
    user_id = request.args.get("userId")
    if not user_id:
        abort(400, "Missing userId")
    _app_user_or_401(user_id)
    bot, _ = _app_bot_member_or_error(user_id, request.args.get("botId"))
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
    except ValueError:
        limit = 50
    messages = db.get_messages(bot_id=bot["bot_id"], user_id=user_id, limit=limit)
    return jsonify({"messages": messages})


# ============================================================================
# HTTP Endpoints: Bot Server → Platform (Bot 的 reply/push API)
# 這些就是 LINE Messaging API 的角色
# ============================================================================

@app.route("/api/v1/bot/reply", methods=["POST"])
@require_bot_token
def bot_api_reply():
    """Bot calls this to reply to a message (like LINE Messaging API reply endpoint)."""
    data = request.get_json(force=True, silent=True) or {}
    reply_token = data.get("replyToken")
    messages = data.get("messages", [])

    if not reply_token:
        return jsonify({"status": "error", "message": "missing replyToken"}), 400
    err = validate_messages(messages)
    if err:
        return jsonify({"status": "error", "message": err}), 400

    user_id = db.get_user_by_reply_token(bot_id(), reply_token)
    if not user_id:
        logger.warning(f"reply_token {reply_token} not found")
        return jsonify({"status": "error", "message": "invalid replyToken"}), 404

    logger.info(f"Bot {bot_id()} reply to {user_id} ({len(messages)} message(s))")
    deliver_to_client(bot_id(), user_id, messages)
    return jsonify({"status": "ok"})


@app.route("/api/v1/bot/push", methods=["POST"])
@require_bot_token
def bot_api_push():
    """Bot calls this to push a message (like LINE Messaging API push endpoint)."""
    data = request.get_json(force=True, silent=True) or {}
    to = data.get("to")
    messages = data.get("messages", [])

    if not to or not is_safe_id(to):
        return jsonify({"status": "error", "message": "missing or invalid 'to'"}), 400
    err = validate_messages(messages)
    if err:
        return jsonify({"status": "error", "message": err}), 400

    if not db.is_member(bot_id(), to):
        return jsonify({"status": "error", "message": "the user has not added this bot as a friend"}), 400
    logger.info(f"Bot {bot_id()} push to {to} ({len(messages)} message(s))")
    deliver_to_client(bot_id(), to, messages)
    return jsonify({"status": "ok"})


@app.route("/api/v1/bot/content/<message_id>", methods=["GET"])
@require_bot_token
def bot_api_content(message_id):
    """Bot calls this to retrieve binary content (like LINE get message content)."""
    if not is_safe_id(message_id):
        abort(400, "Invalid messageId")
    if not db.has_message(bot_id(), message_id):  # 只能下載自己這個 Bot 收到的內容
        abort(404, "Content not found")
    if os.path.exists(MEDIA_DIR):
        for fname in os.listdir(MEDIA_DIR):
            if fname.startswith(f"{message_id}."):
                fpath = os.path.join(MEDIA_DIR, fname)
                with open(fpath, 'rb') as f:
                    return f.read(), 200, {'Content-Type': 'application/octet-stream'}
    abort(404, "Content not found")


@app.route("/api/v1/bot/profile/<user_id>", methods=["GET"])
@require_bot_token
def bot_api_profile(user_id):
    """Bot calls this to retrieve user profile (like LINE get profile)."""
    user = db.get_user(user_id) if is_safe_id(user_id) and db.is_member(bot_id(), user_id) else None
    if user:
        return jsonify({
            "userId": user["user_id"],
            "displayName": user.get("display_name") or f"User_{user_id[:6]}",
            "pictureUrl": None,
            "statusMessage": None,
            "language": "zh-TW"
        })
    return jsonify({
        "userId": user_id,
        "displayName": f"User_{user_id[:6]}",
        "pictureUrl": None,
        "statusMessage": None,
        "language": "zh-TW"
    })



# ============================================================================
# LINE Messaging API 相容端點（/v2/bot/*）
# 讓 localbot.v3（以及官方 line-bot-sdk v3 設定 host 後）可以直接呼叫。
# 回應格式比照 LINE：成功回 sentMessages，錯誤回 {"message": "..."}。
# ============================================================================

def _sent_messages(ids):
    return {"sentMessages": [{"id": mid} for mid in ids]}


def _request_json():
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


@app.route("/v2/bot/message/reply", methods=["POST"])
@require_bot_token
def v2_reply():
    data = _request_json()
    reply_token = data.get("replyToken")
    messages = data.get("messages")
    if not reply_token:
        return line_error("The request body has 1 error(s): replyToken is required")
    err = validate_messages(messages)
    if err:
        return line_error(err)
    user_id = db.get_user_by_reply_token(bot_id(), reply_token)
    if not user_id:
        return line_error("Invalid reply token")
    return jsonify(_sent_messages(deliver_to_client(bot_id(), user_id, messages)))


@app.route("/v2/bot/message/push", methods=["POST"])
@require_bot_token
def v2_push():
    data = _request_json()
    to = data.get("to")
    messages = data.get("messages")
    if not to or not is_safe_id(to):
        return line_error("The property, 'to', in the request body is invalid")
    err = validate_messages(messages)
    if err:
        return line_error(err)
    if not db.is_member(bot_id(), to):
        return line_error("The user hasn't added this bot as a friend")
    return jsonify(_sent_messages(deliver_to_client(bot_id(), to, messages)))


@app.route("/v2/bot/message/multicast", methods=["POST"])
@require_bot_token
def v2_multicast():
    data = _request_json()
    targets = data.get("to")
    messages = data.get("messages")
    if not isinstance(targets, list) or not targets:
        return line_error("The property, 'to', in the request body is invalid")
    if len(targets) > MAX_MULTICAST_TARGETS:
        return line_error(f"'to' must not exceed {MAX_MULTICAST_TARGETS} items")
    if not all(is_safe_id(t) for t in targets):
        return line_error("The property, 'to', contains an invalid user ID")
    err = validate_messages(messages)
    if err:
        return line_error(err)
    for uid in dict.fromkeys(targets):  # 去除重複、保留順序；不是好友的人會被略過（與 LINE 相同）
        if db.is_member(bot_id(), uid):
            deliver_to_client(bot_id(), uid, messages)
    return jsonify({})


def _broadcast(messages):
    user_ids = db.list_user_ids(bot_id())
    for uid in user_ids:
        deliver_to_client(bot_id(), uid, messages)
    return len(user_ids)


@app.route("/v2/bot/message/broadcast", methods=["POST"])
@require_bot_token
def v2_broadcast():
    messages = _request_json().get("messages")
    err = validate_messages(messages)
    if err:
        return line_error(err)
    count = _broadcast(messages)
    logger.info(f"Broadcast to {count} user(s)")
    return jsonify({})


@app.route("/v2/bot/message/narrowcast", methods=["POST"])
@require_bot_token
def v2_narrowcast():
    """LocalBot 沒有受眾 / 屬性資料，narrowcast 一律視同 broadcast。"""
    data = _request_json()
    messages = data.get("messages")
    err = validate_messages(messages)
    if err:
        return line_error(err)
    if data.get("recipient") or data.get("filter"):
        logger.warning("narrowcast: recipient/filter 尚未支援，將送給所有使用者")
    count = _broadcast(messages)
    request_id = uuid.uuid4().hex
    logger.info(f"Narrowcast (as broadcast) to {count} user(s), requestId={request_id}")
    return jsonify({}), 202, {"X-Line-Request-Id": request_id}


@app.route("/v2/bot/message/quota", methods=["GET"])
@require_bot_token
def v2_quota():
    # 自架平台沒有訊息額度限制
    return jsonify({"type": "none"})


@app.route("/v2/bot/message/quota/consumption", methods=["GET"])
@require_bot_token
def v2_quota_consumption():
    return jsonify({"totalUsage": 0})


@app.route("/v2/bot/profile/<user_id>", methods=["GET"])
@require_bot_token
def v2_profile(user_id):
    if not is_safe_id(user_id) or not db.is_member(bot_id(), user_id):
        return line_error("Not found", 404)
    user = db.get_user(user_id)
    if not user:
        return line_error("Not found", 404)
    return jsonify({
        "userId": user["user_id"],
        "displayName": user.get("display_name") or f"User_{user_id[:6]}",
        "language": "zh-TW",
    })


@app.route("/v2/bot/message/<message_id>/content", methods=["GET"])
@require_bot_token
def v2_content(message_id):
    return bot_api_content(message_id)


@app.route("/v2/bot/chat/loading/start", methods=["POST"])
@require_bot_token
def v2_loading_start():
    """顯示「輸入中」動畫（LINE 的 show_loading_animation）。"""
    data = _request_json()
    chat_id = data.get("chatId")
    seconds = data.get("loadingSeconds", 20)
    if not chat_id or not is_safe_id(chat_id):
        return line_error("The property, 'chatId', in the request body is invalid")
    if not isinstance(seconds, int) or seconds < 5 or seconds > 60 or seconds % 5:
        return line_error("loadingSeconds must be a multiple of 5 between 5 and 60")
    if db.is_member(bot_id(), chat_id) and chat_id in connected_users and connected_users[chat_id]:
        socketio.emit("loading", {"botId": bot_id(), "chatId": chat_id, "loadingSeconds": seconds}, room=chat_id)
    return jsonify({}), 202


# ============================================================================
# Rich Menu（聊天室下方的圖文選單）
# Bot 端：與 LINE 相同的 /v2/bot/richmenu*、/v2/bot/user/*/richmenu 端點
# App 端：/richmenu/current、/richmenu/switch、/richmenu/<id>/image
# ============================================================================
def default_richmenu_key(bot_id_value: str) -> str:
    return f"default_richmenu:{bot_id_value}"



def validate_richmenu(data) -> str:
    """回傳錯誤訊息；沒問題回傳空字串。規則比照 LINE。"""
    if not isinstance(data, dict):
        return "The request body is invalid"
    size = data.get("size")
    if not isinstance(size, dict) or not all(isinstance(size.get(k), int) for k in ("width", "height")):
        return "size.width and size.height are required"
    w, h = size["width"], size["height"]
    if not (800 <= w <= 2500) or h < 250 or w / h < 1.45:
        return "size must be 800-2500 px wide, at least 250 px high, with an aspect ratio (width / height) of 1.45 or more"
    if not isinstance(data.get("selected"), bool):
        return "selected is required"
    name = data.get("name")
    if not isinstance(name, str) or not name or len(name) > 300:
        return "name must be 1-300 characters"
    chat_bar = data.get("chatBarText")
    if not isinstance(chat_bar, str) or not chat_bar or len(chat_bar) > 14:
        return "chatBarText must be 1-14 characters"
    areas = data.get("areas")
    if not isinstance(areas, list) or len(areas) > 20:
        return "areas must be an array of up to 20 items"
    for i, area in enumerate(areas):
        bounds = area.get("bounds") if isinstance(area, dict) else None
        if not isinstance(bounds, dict) or not all(isinstance(bounds.get(k), int) for k in ("x", "y", "width", "height")):
            return f"areas[{i}].bounds is invalid"
        if bounds["x"] < 0 or bounds["y"] < 0 or bounds["x"] + bounds["width"] > w or bounds["y"] + bounds["height"] > h:
            return f"areas[{i}].bounds is out of the rich menu"
        action = area.get("action")
        if not isinstance(action, dict) or not isinstance(action.get("type"), str):
            return f"areas[{i}].action is invalid"
    return ""


def _richmenu_public(menu: dict) -> dict:
    return {k: v for k, v in menu.items() if k not in ("imageExt", "botId")}


def _richmenu_for_app(menu):
    if not menu:
        return None
    data = _richmenu_public(menu)
    data["imageUrl"] = f"{SERVER_URL.rstrip('/')}/richmenu/{menu['richMenuId']}/image"
    return data


def effective_richmenu(bot_id_value: str, user_id: str):
    """使用者在這個 Bot 實際看到的選單：個別綁定 > 預設；沒有上傳圖片的選單不顯示。"""
    if db.is_blocked(bot_id_value, user_id):
        return None
    for rid in (db.get_user_richmenu_id(bot_id_value, user_id), db.get_setting(default_richmenu_key(bot_id_value))):
        if rid:
            menu = db.get_richmenu(bot_id_value, rid)
            if menu and menu.get("imageExt"):
                return menu
    return None


def notify_richmenu_changed(bot_id_value: str, user_ids=None):
    """通知 App 重新載入這個 Bot 的選單；user_ids 為 None 表示這個 Bot 所有連線中的好友。"""
    if user_ids is None:
        targets = [u for u in db.list_user_ids(bot_id_value, include_blocked=True) if u in connected_users]
    else:
        targets = user_ids
    for uid in targets:
        if uid in connected_users and connected_users[uid]:
            socketio.emit("richmenu_changed", {"botId": bot_id_value}, room=uid)


def _require_richmenu(richmenu_id):
    if not is_safe_id(richmenu_id):
        return None
    return db.get_richmenu(bot_id(), richmenu_id)


@app.route("/v2/bot/richmenu/validate", methods=["POST"])
@require_bot_token
def v2_richmenu_validate():
    err = validate_richmenu(request.get_json(force=True, silent=True))
    return line_error(err) if err else jsonify({})


@app.route("/v2/bot/richmenu", methods=["POST"])
@require_bot_token
def v2_richmenu_create():
    data = request.get_json(force=True, silent=True)
    err = validate_richmenu(data)
    if err:
        return line_error(err)
    allowed = ("size", "selected", "name", "chatBarText", "areas")
    richmenu_id = f"richmenu-{uuid.uuid4().hex}"
    db.create_richmenu(bot_id(), richmenu_id, {k: data[k] for k in allowed})
    logger.info(f"Rich menu created: {richmenu_id}")
    return jsonify({"richMenuId": richmenu_id})


@app.route("/v2/bot/richmenu/list", methods=["GET"])
@require_bot_token
def v2_richmenu_list():
    return jsonify({"richmenus": [_richmenu_public(m) for m in db.list_richmenus(bot_id())]})


@app.route("/v2/bot/richmenu/<richmenu_id>", methods=["GET"])
@require_bot_token
def v2_richmenu_get(richmenu_id):
    menu = _require_richmenu(richmenu_id)
    return jsonify(_richmenu_public(menu)) if menu else line_error("Not found", 404)


@app.route("/v2/bot/richmenu/<richmenu_id>", methods=["DELETE"])
@require_bot_token
def v2_richmenu_delete(richmenu_id):
    menu = _require_richmenu(richmenu_id)
    if not menu:
        return line_error("Not found", 404)
    was_default = db.get_setting(default_richmenu_key(bot_id())) == richmenu_id
    affected = db.users_with_richmenu(bot_id(), richmenu_id)
    if menu.get("imageExt"):
        try:
            os.remove(os.path.join(RICHMENU_DIR, f"{richmenu_id}.{menu['imageExt']}"))
        except OSError:
            pass
    db.delete_richmenu(bot_id(), richmenu_id)
    notify_richmenu_changed(bot_id(), None if was_default else affected)
    return jsonify({})


def _detect_image(data: bytes, allow_webp: bool = False):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if allow_webp and len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@app.route("/v2/bot/richmenu/<richmenu_id>/content", methods=["POST"])
@require_bot_token
def v2_richmenu_upload(richmenu_id):
    menu = _require_richmenu(richmenu_id)
    if not menu:
        return line_error("Not found", 404)
    if menu.get("imageExt"):
        return line_error("An image has already been uploaded to the richmenu")
    content_type = (request.content_type or "").split(";")[0].strip().lower()
    if content_type not in ("image/png", "image/jpeg"):
        return line_error("Content-Type must be image/png or image/jpeg", 415)
    data = request.get_data()
    if not data or len(data) > RICHMENU_MAX_IMAGE_BYTES:
        return line_error("The image must be 1 MB or smaller", 413 if data else 400)
    ext = _detect_image(data)
    if ext is None:
        return line_error("The image is not a valid PNG or JPEG")
    with open(os.path.join(RICHMENU_DIR, f"{richmenu_id}.{ext}"), "wb") as f:
        f.write(data)
    db.set_richmenu_image(richmenu_id, ext)
    is_default = db.get_setting(default_richmenu_key(bot_id())) == richmenu_id
    notify_richmenu_changed(bot_id(), None if is_default else db.users_with_richmenu(bot_id(), richmenu_id))
    return jsonify({})


def _send_richmenu_image(menu):
    if not menu or not menu.get("imageExt"):
        abort(404)
    richmenu_id = menu["richMenuId"]
    return send_from_directory(RICHMENU_DIR, f"{richmenu_id}.{menu['imageExt']}")


@app.route("/v2/bot/richmenu/<richmenu_id>/content", methods=["GET"])
@require_bot_token
def v2_richmenu_download(richmenu_id):
    return _send_richmenu_image(_require_richmenu(richmenu_id))


def _richmenu_ready(richmenu_id):
    """連結前檢查：選單存在且已上傳圖片（與 LINE 相同）。"""
    menu = _require_richmenu(richmenu_id)
    if not menu:
        return line_error("Not found", 404)
    if not menu.get("imageExt"):
        return line_error("must upload richmenu image before applying it to user")
    return None


@app.route("/v2/bot/user/all/richmenu/<richmenu_id>", methods=["POST"])
@require_bot_token
def v2_richmenu_set_default(richmenu_id):
    err = _richmenu_ready(richmenu_id)
    if err:
        return err
    db.set_setting(default_richmenu_key(bot_id()), richmenu_id)
    notify_richmenu_changed(bot_id())
    return jsonify({})


@app.route("/v2/bot/user/all/richmenu", methods=["GET"])
@require_bot_token
def v2_richmenu_get_default():
    rid = db.get_setting(default_richmenu_key(bot_id()))
    return jsonify({"richMenuId": rid}) if rid else line_error("no default richmenu", 404)


@app.route("/v2/bot/user/all/richmenu", methods=["DELETE"])
@require_bot_token
def v2_richmenu_cancel_default():
    db.set_setting(default_richmenu_key(bot_id()), None)
    notify_richmenu_changed(bot_id())
    return jsonify({})


@app.route("/v2/bot/user/<user_id>/richmenu/<richmenu_id>", methods=["POST"])
@require_bot_token
def v2_richmenu_link(user_id, richmenu_id):
    if not is_safe_id(user_id):
        return line_error("Invalid user ID")
    err = _richmenu_ready(richmenu_id)
    if err:
        return err
    if not db.is_member(bot_id(), user_id):
        return line_error("Not found", 404)
    db.link_richmenu(bot_id(), user_id, richmenu_id)
    notify_richmenu_changed(bot_id(), [user_id])
    return jsonify({})


@app.route("/v2/bot/user/<user_id>/richmenu", methods=["GET"])
@require_bot_token
def v2_richmenu_of_user(user_id):
    rid = db.get_user_richmenu_id(bot_id(), user_id) if is_safe_id(user_id) else None
    return jsonify({"richMenuId": rid}) if rid else line_error("the user has no richmenu", 404)


@app.route("/v2/bot/user/<user_id>/richmenu", methods=["DELETE"])
@require_bot_token
def v2_richmenu_unlink(user_id):
    if not is_safe_id(user_id):
        return line_error("Invalid user ID")
    db.unlink_richmenu(bot_id(), user_id)
    notify_richmenu_changed(bot_id(), [user_id])
    return jsonify({})


def _user_ids_from_body(data, limit=500):
    ids = data.get("userIds")
    if not isinstance(ids, list) or not ids or len(ids) > limit or not all(is_safe_id(u) for u in ids):
        return None
    return list(dict.fromkeys(ids))


@app.route("/v2/bot/richmenu/bulk/link", methods=["POST"])
@require_bot_token
def v2_richmenu_bulk_link():
    data = _request_json()
    user_ids = _user_ids_from_body(data)
    if user_ids is None:
        return line_error("userIds must be an array of 1-500 user IDs")
    err = _richmenu_ready(data.get("richMenuId"))
    if err:
        return err
    user_ids = [u for u in user_ids if db.is_member(bot_id(), u)]  # 不是好友的略過
    for uid in user_ids:
        db.link_richmenu(bot_id(), uid, data["richMenuId"])
    notify_richmenu_changed(bot_id(), user_ids)
    return jsonify({}), 202


@app.route("/v2/bot/richmenu/bulk/unlink", methods=["POST"])
@require_bot_token
def v2_richmenu_bulk_unlink():
    user_ids = _user_ids_from_body(_request_json())
    if user_ids is None:
        return line_error("userIds must be an array of 1-500 user IDs")
    for uid in user_ids:
        db.unlink_richmenu(bot_id(), uid)
    notify_richmenu_changed(bot_id(), user_ids)
    return jsonify({}), 202


@app.route("/v2/bot/richmenu/alias", methods=["POST"])
@require_bot_token
def v2_richmenu_alias_create():
    data = _request_json()
    alias_id = data.get("richMenuAliasId")
    if not is_safe_id(alias_id) or len(alias_id) > 32:
        return line_error("richMenuAliasId must be 1-32 characters")
    if not _require_richmenu(data.get("richMenuId")):
        return line_error("richmenu not found")
    if db.get_richmenu_alias(bot_id(), alias_id):
        return line_error("conflict richmenu alias id")
    db.set_richmenu_alias(bot_id(), alias_id, data["richMenuId"])
    return jsonify({})


@app.route("/v2/bot/richmenu/alias/list", methods=["GET"])
@require_bot_token
def v2_richmenu_alias_list():
    return jsonify({"aliases": db.list_richmenu_aliases(bot_id())})


@app.route("/v2/bot/richmenu/alias/<alias_id>", methods=["GET"])
@require_bot_token
def v2_richmenu_alias_get(alias_id):
    rid = db.get_richmenu_alias(bot_id(), alias_id) if is_safe_id(alias_id) else None
    if not rid:
        return line_error("Not found", 404)
    return jsonify({"richMenuAliasId": alias_id, "richMenuId": rid})


@app.route("/v2/bot/richmenu/alias/<alias_id>", methods=["POST"])
@require_bot_token
def v2_richmenu_alias_update(alias_id):
    if not is_safe_id(alias_id) or not db.get_richmenu_alias(bot_id(), alias_id):
        return line_error("Not found", 404)
    rid = _request_json().get("richMenuId")
    if not _require_richmenu(rid):
        return line_error("richmenu not found")
    db.set_richmenu_alias(bot_id(), alias_id, rid)
    return jsonify({})


@app.route("/v2/bot/richmenu/alias/<alias_id>", methods=["DELETE"])
@require_bot_token
def v2_richmenu_alias_delete(alias_id):
    if not is_safe_id(alias_id) or not db.delete_richmenu_alias(bot_id(), alias_id):
        return line_error("Not found", 404)
    return jsonify({})


# ---- App 端 ----
@app.route("/richmenu/current", methods=["GET"])
def app_richmenu_current():
    user_id = request.args.get("userId", "")
    _app_user_or_401(user_id)
    bot, _ = _app_bot_member_or_error(user_id, request.args.get("botId"))
    return jsonify({"richMenu": _richmenu_for_app(effective_richmenu(bot["bot_id"], user_id))})


@app.route("/richmenu/switch", methods=["POST"])
def app_richmenu_switch():
    """richmenuswitch 動作：把使用者的選單切換成別名指向的選單。"""
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("userId", "")
    alias_id = data.get("richMenuAliasId", "")
    _app_user_or_401(user_id)
    bot, _ = _app_bot_member_or_error(user_id, data.get("botId"))
    rid = db.get_richmenu_alias(bot["bot_id"], alias_id) if is_safe_id(alias_id) else None
    menu = db.get_richmenu(bot["bot_id"], rid) if rid else None
    if not menu or not menu.get("imageExt"):
        return jsonify({"status": "RICHMENU_ALIAS_ID_NOTFOUND", "richMenu": None}), 404
    db.link_richmenu(bot["bot_id"], user_id, rid)
    return jsonify({"status": "SUCCESS", "richMenu": _richmenu_for_app(menu)})


@app.route("/richmenu/<richmenu_id>/image", methods=["GET"])
def app_richmenu_image(richmenu_id):
    # 選單 ID 是不可猜的亂數，所以圖片不需要登入（與其他媒體檔相同）
    return _send_richmenu_image(db.get_richmenu_any(richmenu_id) if is_safe_id(richmenu_id) else None)


# ============================================================================
# Socket.IO Event Handlers (Flutter App real-time connection)
# ============================================================================

@socketio.on("connect")
def handle_connect(auth):
    user_id = None
    token = None
    if isinstance(auth, dict):
        user_id = auth.get("userId")
        token = auth.get("token")
    if not user_id:
        user_id = request.args.get("userId")
    if not token:
        token = request.args.get("token")

    if not user_id or not is_safe_id(user_id):
        logger.warning(f"Connection rejected: missing userId (sid={request.sid})")
        return False
    # 必須持有正確 token，否則任何人都能冒用 userId 偷聽訊息
    if not verify_user_token(user_id, token):
        logger.warning(f"Connection rejected: invalid token for {user_id} (sid={request.sid})")
        return False
    db.touch_user(user_id)

    join_room(user_id)
    if user_id not in connected_users:
        connected_users[user_id] = set()
    connected_users[user_id].add(request.sid)

    logger.info(f"User connected: {user_id} (sid={request.sid})")

    # Send any queued offline messages
    offline_msgs = db.pop_offline_messages(user_id)
    if offline_msgs:
        logger.info(f"Flushing {len(offline_msgs)} offline message(s) to user {user_id}")
        for msg in offline_msgs:
            emit("bot_message", msg, room=user_id)


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    for user_id, sids in list(connected_users.items()):
        if sid in sids:
            sids.remove(sid)
            leave_room(user_id)
            logger.info(f"User disconnected: {user_id} (sid={sid})")
            if not sids:
                del connected_users[user_id]
            break


def disconnect_user(user_id: str):
    """撤銷金鑰或刪除使用者時，立刻切斷他目前的 Socket.IO 連線。"""
    for sid in list(connected_users.get(user_id, ())):
        try:
            socketio.server.disconnect(sid)
        except Exception:  # noqa: BLE001
            logger.exception(f"無法中斷連線 {sid}")


ensure_default_bot()


# ============================================================================
# 背景工作：Webhook 重試、排程推播、紀錄清理
# ============================================================================
webhook_delivery.init(sys.modules[__name__])
scheduled_push.init(sys.modules[__name__])


def start_background_workers():
    """啟動背景執行緒（python app.py 時自動呼叫；用 gunicorn 等方式啟動時請自行呼叫一次）。"""
    if not WORKERS_ENABLED:
        logger.warning("背景工作已停用（LOCALBOT_WORKERS_ENABLED=false）：不會重試 webhook、也不會執行排程推播")
        return None
    import workers
    return workers.start(sys.modules[__name__])


# ============================================================================
# 管理後台（/admin）：程式在 admin_panel.py，這裡只負責掛載
# ============================================================================
if ADMIN_ENABLED:
    import admin_panel
    admin_panel.init_admin(app, sys.modules[__name__])


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    logger.info(f"LocalBot Platform starting on {HOST}:{PORT}")
    logger.info(f"Bot Webhook URL: {BOT_WEBHOOK_URL}")
    logger.info(f"Public Server URL: {SERVER_URL}")
    if ADMIN_ENABLED:
        logger.info(f"管理後台：{SERVER_URL.rstrip('/')}/admin")
    if DEBUG:
        logger.warning("DEBUG 模式已開啟，請勿在公開網路上使用！")
    start_background_workers()
    socketio.run(app, host=HOST, port=PORT, debug=DEBUG, allow_unsafe_werkzeug=True)
