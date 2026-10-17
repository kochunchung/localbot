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
# 預設 Bot 的 Webhook URL
#   多 Bot 之後，Bot 的設定（Webhook URL、金鑰）存在資料庫、由管理後台管理。
#   這裡的 BOT_WEBHOOK_URL、CHANNEL_SECRET、CHANNEL_ACCESS_TOKEN 只在「第一次啟動、資料庫還沒有任何 Bot」時
#   用來建立名為「預設 Bot」的第一個 Bot（從舊版升級時，原本的 Bot 程式不用改任何設定）。
# ============================================================================
BOT_WEBHOOK_URL = os.environ.get("LOCALBOT_BOT_WEBHOOK_URL", "http://localhost:9000/callback")

# ============================================================================
# 金鑰
#   CHANNEL_SECRET        預設 Bot：平台 → Bot 的 Webhook HMAC 簽名（等同 LINE Channel Secret）
#   CHANNEL_ACCESS_TOKEN  預設 Bot：Bot → 平台 API 的 Bearer Token（等同 LINE Channel Access Token）
#   手機 App 不再使用共用金鑰：每個使用者／裝置用邀請碼加入 Bot 時，由伺服器發給自己的金鑰（可單獨撤銷）。
# ============================================================================
SECRETS_FILE = os.environ.get("LOCALBOT_SECRETS_FILE", os.path.join(BASE_DIR, ".localbot_secrets.json"))


_SECRET_NAMES = ("CHANNEL_SECRET", "CHANNEL_ACCESS_TOKEN", "FLASK_SECRET_KEY", "ADMIN_PASSWORD")
_newly_generated = set()


def _new_secret(name: str) -> str:
    # 管理員密碼要人工輸入，用較短（16 字元）的隨機字串；其餘用 43 字元
    return secrets.token_urlsafe(12 if name == "ADMIN_PASSWORD" else 32)


def _load_or_create_secrets() -> dict:
    data = {}
    if os.path.exists(SECRETS_FILE):
        try:
            with open(SECRETS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    changed = False
    for key in _SECRET_NAMES:
        if not data.get(key):
            data[key] = _new_secret(key)
            _newly_generated.add(key)
            changed = True
    if changed:
        try:
            _write_secrets_file(data)
            print(f"[LocalBot] 已產生新的隨機金鑰並儲存於 {SECRETS_FILE}（請勿上傳到 GitHub）")
        except Exception as e:
            print(f"[LocalBot] 無法寫入金鑰檔 {SECRETS_FILE}: {e}")
    return data


def _write_secrets_file(data: dict) -> None:
    """原子寫入金鑰檔（先寫暫存檔再取代），並盡量限制只有本人可讀。"""
    tmp = SECRETS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, SECRETS_FILE)


_generated = _load_or_create_secrets()


def _env(name: str):
    return os.environ.get(f"LOCALBOT_{name}") or None


CHANNEL_SECRET = _env("CHANNEL_SECRET") or _generated["CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = _env("CHANNEL_ACCESS_TOKEN") or _generated["CHANNEL_ACCESS_TOKEN"]
FLASK_SECRET_KEY = _env("FLASK_SECRET_KEY") or _generated["FLASK_SECRET_KEY"]

# ============================================================================
# 管理後台（/admin）
#   ADMIN_PASSWORD 沒有設定 LOCALBOT_ADMIN_PASSWORD 時，第一次啟動自動產生並存入金鑰檔。
# ============================================================================
ADMIN_ENABLED = os.environ.get("LOCALBOT_ADMIN_ENABLED", "true").lower() in ("1", "true", "yes")
ADMIN_PASSWORD = _env("ADMIN_PASSWORD") or _generated["ADMIN_PASSWORD"]
ADMIN_SESSION_HOURS = max(1, int(os.environ.get("LOCALBOT_ADMIN_SESSION_HOURS", "8")))

# 各金鑰的來源：環境變數覆蓋時後台無法修改（只能改環境變數）
SECRET_SOURCES = {name: ("env" if _env(name) else "file") for name in _SECRET_NAMES}

if "ADMIN_PASSWORD" in _newly_generated and SECRET_SOURCES["ADMIN_PASSWORD"] == "file":
    print(f"[LocalBot] 後台管理密碼（只在首次產生時顯示；之後可在 {SECRETS_FILE} 查看）：{ADMIN_PASSWORD}")


def save_secret(name: str, value: str) -> None:
    """更新金鑰檔中的某個金鑰，並同步更新本模組的值。環境變數覆蓋的金鑰不可改。"""
    if name not in _SECRET_NAMES:
        raise KeyError(name)
    if SECRET_SOURCES.get(name) == "env":
        raise PermissionError(f"{name} 由環境變數 LOCALBOT_{name} 設定，無法在執行中修改")
    data = {}
    try:
        with open(SECRETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data[name] = value
    _write_secrets_file(data)
    globals()[name] = value


def new_secret(name: str) -> str:
    return _new_secret(name)


# ============================================================================
# Webhook 轉送 / 日誌 / 排程
# ============================================================================
def _parse_delays(raw: str, default):
    """'10,60,300' → [10, 60, 300]；空字串代表關閉自動重試；格式錯誤則使用預設值。"""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        values = [int(x) for x in raw.split(",") if x.strip()]
        if not values or len(values) > 10 or any(v < 1 for v in values):
            raise ValueError
        return values
    except ValueError:
        print(f"[LocalBot] LOCALBOT_WEBHOOK_RETRY_DELAYS 格式不正確（{raw!r}），改用預設值")
        return list(default)


_DEFAULT_RETRY_DELAYS = [10, 60, 300, 1800]
# 轉送失敗時，第 N 次重試前等待的秒數；清單長度 = 最多重試次數（總嘗試次數 = 1 + 長度）。空字串 = 不自動重試
WEBHOOK_RETRY_DELAYS = _parse_delays(os.environ.get("LOCALBOT_WEBHOOK_RETRY_DELAYS", "10,60,300,1800"), _DEFAULT_RETRY_DELAYS)
WEBHOOK_TIMEOUT = max(1, int(os.environ.get("LOCALBOT_WEBHOOK_TIMEOUT", "15")))
# 轉送紀錄、排程執行紀錄保留天數
LOG_RETENTION_DAYS = max(1, int(os.environ.get("LOCALBOT_LOG_RETENTION_DAYS", "30")))
# 排程錯過時間（例如伺服器關機）後，超過這個分鐘數就不補送
SCHEDULE_GRACE_MINUTES = max(0, int(os.environ.get("LOCALBOT_SCHEDULE_GRACE_MINUTES", "60")))
# 背景工作（重試 / 排程）；用 gunicorn 等其他方式啟動時請自行呼叫 app.start_background_workers()
WORKERS_ENABLED = os.environ.get("LOCALBOT_WORKERS_ENABLED", "true").lower() in ("1", "true", "yes")

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
    # 一般檔案（檔案訊息）
    "pdf", "txt", "csv", "json", "zip",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp",
}
# 這些副檔名以「下載」方式提供，避免瀏覽器直接開啟
DOWNLOAD_ONLY_EXTENSIONS = {
    "pdf", "txt", "csv", "json", "zip",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp",
}
IMAGEMAP_DIR = os.path.join(MEDIA_DIR, "imagemap")
RICHMENU_DIR = os.path.join(MEDIA_DIR, "richmenu")
RICHMENU_MAX_IMAGE_BYTES = 1024 * 1024  # 與 LINE 相同：Rich Menu 圖片最大 1 MB
AVATAR_DIR = os.path.join(MEDIA_DIR, "avatars")  # 每個 Bot 的頭像（後台上傳）
AVATAR_MAX_BYTES = 1024 * 1024

# Create media directories if not existing
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(STICKER_DIR, exist_ok=True)
os.makedirs(IMAGEMAP_DIR, exist_ok=True)
os.makedirs(RICHMENU_DIR, exist_ok=True)
os.makedirs(AVATAR_DIR, exist_ok=True)
