"""
Configuration settings for LocalBot Server (LINE Platform Emulator).

所有設定都可用環境變數覆寫。
三組金鑰若沒有設定環境變數，第一次啟動時會自動產生隨機值，
存到 server/.localbot_secrets.json（已列入 .gitignore，請勿上傳）。
"""
import os
import json
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================================
# app.py 本身的配置 (扮演 LINE 平台角色)
# ============================================================================
# 你的平台對外 HTTPS 網址（例如經過 Cloudflare Tunnel / Nginx 的網域）
SERVER_URL = os.environ.get("LOCALBOT_SERVER_URL", "http://localhost:5003")
HOST = os.environ.get("LOCALBOT_HOST", "0.0.0.0")
PORT = int(os.environ.get("LOCALBOT_PORT", "5003"))

# 只在本機開發時開啟；正式環境務必維持 false（Werkzeug debugger 可被遠端執行程式碼）
DEBUG = os.environ.get("LOCALBOT_DEBUG", "false").lower() in ("1", "true", "yes")

# Socket.IO 允許的來源，逗號分隔；"*" 代表全部（手機 App 不受 CORS 影響）
_cors = os.environ.get("LOCALBOT_CORS_ORIGINS", "*").strip()
CORS_ALLOWED_ORIGINS = "*" if _cors == "*" else [o.strip() for o in _cors.split(",") if o.strip()]

# ============================================================================
# 你的 Bot 程式的 Webhook URL
# ============================================================================
BOT_WEBHOOK_URL = os.environ.get("LOCALBOT_BOT_WEBHOOK_URL", "http://localhost:9000/callback")

# ============================================================================
# 金鑰
#   CHANNEL_SECRET        平台 → Bot 的 Webhook HMAC 簽名（等同 LINE Channel Secret，只給 Bot）
#   CHANNEL_ACCESS_TOKEN  Bot → 平台 API 的 Bearer Token（等同 LINE Channel Access Token，只給 Bot）
#   APP_SECRET            手機 App → 平台 的 HMAC 簽名金鑰（填在 App 設定頁）
# ============================================================================
SECRETS_FILE = os.environ.get("LOCALBOT_SECRETS_FILE", os.path.join(BASE_DIR, ".localbot_secrets.json"))


def _load_or_create_secrets() -> dict:
    data = {}
    if os.path.exists(SECRETS_FILE):
        try:
            with open(SECRETS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    changed = False
    for key in ("CHANNEL_SECRET", "CHANNEL_ACCESS_TOKEN", "APP_SECRET", "FLASK_SECRET_KEY"):
        if not data.get(key):
            data[key] = secrets.token_urlsafe(32)
            changed = True
    if changed:
        try:
            with open(SECRETS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[LocalBot] 已產生新的隨機金鑰並儲存於 {SECRETS_FILE}（請勿上傳到 GitHub）")
        except Exception as e:
            print(f"[LocalBot] 無法寫入金鑰檔 {SECRETS_FILE}: {e}")
    return data


_generated = _load_or_create_secrets()

CHANNEL_SECRET = os.environ.get("LOCALBOT_CHANNEL_SECRET") or _generated["CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = os.environ.get("LOCALBOT_CHANNEL_ACCESS_TOKEN") or _generated["CHANNEL_ACCESS_TOKEN"]
APP_SECRET = os.environ.get("LOCALBOT_APP_SECRET") or _generated["APP_SECRET"]
FLASK_SECRET_KEY = os.environ.get("LOCALBOT_FLASK_SECRET_KEY") or _generated["FLASK_SECRET_KEY"]

# ============================================================================
# 資料儲存 / 上傳限制
# ============================================================================
DATABASE_PATH = os.environ.get("LOCALBOT_DB_PATH", os.path.join(BASE_DIR, "localbot.db"))
MEDIA_DIR = os.environ.get("LOCALBOT_MEDIA_DIR", os.path.join(BASE_DIR, "media"))
STICKER_DIR = os.path.join(MEDIA_DIR, "stickers")
MAX_UPLOAD_MB = int(os.environ.get("LOCALBOT_MAX_UPLOAD_MB", "20"))
ALLOWED_UPLOAD_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "webp", "heic",
    "m4a", "aac", "mp3", "wav", "ogg", "opus",
    "mp4", "mov", "3gp", "webm",
}

# Create media directories if not existing
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(STICKER_DIR, exist_ok=True)
