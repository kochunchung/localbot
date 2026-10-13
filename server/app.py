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
import uuid
import time
import json
import logging
import requests as http_requests
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_socketio import SocketIO, emit, join_room, leave_room

from localconfig import (
    SERVER_URL, HOST, PORT, CHANNEL_ACCESS_TOKEN, CHANNEL_SECRET, APP_SECRET,
    FLASK_SECRET_KEY, DEBUG, CORS_ALLOWED_ORIGINS, MAX_UPLOAD_MB,
    ALLOWED_UPLOAD_EXTENSIONS, DATABASE_PATH, MEDIA_DIR, STICKER_DIR, BOT_WEBHOOK_URL
)
from database import Database
from localbot.utils import calculate_signature, check_signature

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
def user_token(user_id: str) -> str:
    """App 端用 APP_SECRET 對 userId 做 HMAC，當作該使用者的存取憑證。"""
    return calculate_signature(APP_SECRET, user_id)


def verify_user_token(user_id, token) -> bool:
    if not user_id or not token or not isinstance(token, str):
        return False
    return hmac.compare_digest(user_token(user_id), token)


def require_bot_token(func):
    """Bot → 平台 API 必須帶 Authorization: Bearer <CHANNEL_ACCESS_TOKEN>。"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token or not hmac.compare_digest(token, CHANNEL_ACCESS_TOKEN):
            return jsonify({"status": "error", "message": "invalid access token"}), 401
        return func(*args, **kwargs)
    return wrapper


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    return resp


# ============================================================================
# Helper: Push messages to Flutter App via Socket.IO (or offline queue)
# ============================================================================
def deliver_to_client(user_id: str, messages: list):
    """Deliver messages to Flutter App (online: Socket.IO, offline: enqueue)."""
    for msg in messages:
        msg_id = f"bot_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        msg_data = {
            "messageId": msg_id,
            "userId": user_id,
            "direction": "outgoing",
            "messageType": msg.get("type", "text"),
            "content": msg,
            "createdAt": int(time.time() * 1000)
        }

        db.save_message(
            message_id=msg_id,
            user_id=user_id,
            direction="outgoing",
            message_type=msg.get("type", "text"),
            content=msg
        )

        if user_id in connected_users and connected_users[user_id]:
            socketio.emit("bot_message", msg_data, room=user_id)
            logger.info(f"Delivered message {msg_id} via Socket.IO to {user_id}")
        else:
            db.enqueue_offline_message(user_id, msg_data)
            logger.info(f"User {user_id} offline, enqueued message {msg_id}")


def forward_to_bot(body: str, signature: str):
    """Forward webhook event to user's Bot server (like LINE Platform does)."""
    try:
        res = http_requests.post(
            BOT_WEBHOOK_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Line-Signature": signature,
                "X-LocalBot-Signature": signature,
            },
            timeout=15,
        )
        logger.info(f"Forwarded webhook to {BOT_WEBHOOK_URL}, status={res.status_code}")
        return res.status_code
    except Exception as e:
        logger.error(f"Failed to forward webhook to {BOT_WEBHOOK_URL}: {e}")
        return 500


# ============================================================================
# HTTP Endpoints: Flutter App → Platform
# ============================================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "LocalBot Platform",
        "version": "2.1.0",
    })


@app.route("/register", methods=["POST"])
def register():
    """Device registration endpoint."""
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("userId") or str(uuid.uuid4())
    display_name = str(data.get("displayName", "LocalBot User"))[:64]

    if not is_safe_id(user_id):
        abort(400, "Invalid userId")
    # 必須持有 APP_SECRET 才能註冊（避免陌生人灌假帳號）
    if not verify_user_token(user_id, request.headers.get("X-LocalBot-Token")):
        abort(401, "Invalid app token")

    # 注意：絕對不要把 CHANNEL_SECRET 回傳給 App
    db.register_user(user_id=user_id, device_secret="-", display_name=display_name)
    logger.info(f"Registered user: {user_id} ({display_name})")

    return jsonify({
        "status": "success",
        "userId": user_id,
        "serverUrl": SERVER_URL
    })


@app.route("/callback", methods=["POST"])
def callback():
    """
    Receive messages from Flutter App, then forward to Bot server.
    This is what LINE Platform does: receive from LINE App, forward to Bot webhook.
    """
    body = request.get_data(as_text=True)
    if not body:
        abort(400, "Empty request body")

    # 驗證 App 用 APP_SECRET 產生的簽名
    signature = request.headers.get("X-LocalBot-Signature") or request.headers.get("X-Line-Signature")
    if not check_signature(APP_SECRET, body, signature or ""):
        logger.warning("Rejected /callback: invalid signature")
        abort(401, "Invalid signature")

    try:
        payload = json.loads(body)
    except Exception:
        abort(400, "Malformed JSON")
    if not isinstance(payload, dict):
        abort(400, "Malformed JSON")

    # Save reply_tokens and incoming messages to DB
    events = payload.get("events", [])
    if not isinstance(events, list):
        abort(400, "Malformed events")
    for ev in events:
        if not isinstance(ev, dict):
            continue
        reply_token = ev.get("replyToken") or ev.get("reply_token")
        source = ev.get("source", {}) or {}
        user_id = source.get("userId") or source.get("user_id")
        if user_id and not is_safe_id(user_id):
            abort(400, "Invalid userId")

        if reply_token and user_id:
            db.save_reply_token(reply_token, user_id)

        if ev.get("type") == "message" and user_id:
            msg = ev.get("message", {})
            msg_id = str(msg.get("id", uuid.uuid4().hex))
            db.save_message(
                message_id=msg_id,
                user_id=user_id,
                direction="incoming",
                message_type=msg.get("type", "text"),
                content=msg
            )
        elif ev.get("type") == "postback" and user_id:
            pb = ev.get("postback", {})
            db.save_message(
                message_id=f"pb_{int(time.time()*1000)}",
                user_id=user_id,
                direction="incoming",
                message_type="postback",
                content=pb
            )

    # Sign and forward to Bot server (just like LINE Platform)
    signature = calculate_signature(CHANNEL_SECRET, body)
    status = forward_to_bot(body, signature)

    if status >= 400:
        return jsonify({"status": "error", "message": f"Bot returned {status}"}), 502

    return "OK", 200


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
    return send_from_directory(MEDIA_DIR, filename)


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
    if not verify_user_token(user_id, request.headers.get("X-LocalBot-Token")):
        abort(401, "Invalid app token")
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
    except ValueError:
        limit = 50
    messages = db.get_messages(user_id=user_id, limit=limit)
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

    user_id = db.get_user_by_reply_token(reply_token)
    if not user_id:
        logger.warning(f"reply_token {reply_token} not found")
        return jsonify({"status": "error", "message": "invalid replyToken"}), 404

    logger.info(f"Bot reply to {user_id} ({len(messages)} message(s))")
    deliver_to_client(user_id, messages)
    return jsonify({"status": "ok"})


@app.route("/api/v1/bot/push", methods=["POST"])
@require_bot_token
def bot_api_push():
    """Bot calls this to push a message (like LINE Messaging API push endpoint)."""
    data = request.get_json(force=True, silent=True) or {}
    to = data.get("to")
    messages = data.get("messages", [])

    if not to:
        return jsonify({"status": "error", "message": "missing 'to'"}), 400

    logger.info(f"Bot push to {to} ({len(messages)} message(s))")
    deliver_to_client(to, messages)
    return jsonify({"status": "ok"})


@app.route("/api/v1/bot/content/<message_id>", methods=["GET"])
@require_bot_token
def bot_api_content(message_id):
    """Bot calls this to retrieve binary content (like LINE get message content)."""
    if not is_safe_id(message_id):
        abort(400, "Invalid messageId")
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
    user = db.get_user(user_id)
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


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    logger.info(f"LocalBot Platform starting on {HOST}:{PORT}")
    logger.info(f"Bot Webhook URL: {BOT_WEBHOOK_URL}")
    logger.info(f"Public Server URL: {SERVER_URL}")
    if DEBUG:
        logger.warning("DEBUG 模式已開啟，請勿在公開網路上使用！")
    socketio.run(app, host=HOST, port=PORT, debug=DEBUG, allow_unsafe_werkzeug=True)
