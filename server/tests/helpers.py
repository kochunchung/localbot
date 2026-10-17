"""測試共用工具：隔離的資料庫、預設 Bot、使用者（含金鑰與好友關係）。"""
import os
import tempfile

TMP = tempfile.mkdtemp()
os.environ.setdefault("LOCALBOT_SECRETS_FILE", os.path.join(TMP, "secrets.json"))
os.environ.setdefault("LOCALBOT_MEDIA_DIR", os.path.join(TMP, "media"))
os.environ.setdefault("LOCALBOT_DB_PATH", os.path.join(TMP, "test.db"))

import app as platform_app  # noqa: E402
from database import Database  # noqa: E402
from localconfig import CHANNEL_ACCESS_TOKEN, CHANNEL_SECRET  # noqa: E402

DEFAULT_BOT = "default"
BOT_HEADERS = {"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"}  # 預設 Bot 的 Bot 端金鑰
TOKENS = {}  # user_id → 明文金鑰


def fresh_db(name: str) -> Database:
    """換成全新的資料庫（含預設 Bot），並重置加入頻率限制。"""
    db = Database(os.path.join(TMP, f"{name}.db"))
    platform_app.db = db
    platform_app.ensure_default_bot()
    platform_app.reset_join_limiter()
    TOKENS.clear()
    return db


def make_user(uid: str, bots=(DEFAULT_BOT,), name=None, blocked=False) -> dict:
    """直接在資料庫建立使用者、金鑰與好友關係；回傳 App 端要帶的標頭。"""
    db = platform_app.db
    token = platform_app.new_user_token()
    db.create_user(uid, name or uid, platform_app.hash_token(token))
    for bot_id in bots:
        db.add_membership(bot_id, uid)
        if blocked:
            db.set_blocked(bot_id, uid, True)
    TOKENS[uid] = token
    return app_headers(uid)


def app_headers(uid: str) -> dict:
    return {"X-LocalBot-Token": TOKENS.get(uid, "lbu_invalid")}


def make_bot(bot_id: str, name=None, webhook_url="http://bot.invalid/callback", enabled=True):
    """建立另一個 Bot；回傳 (bot dict, Bot 端標頭)。"""
    platform_app.db.create_bot(bot_id, name or bot_id, None, f"secret-{bot_id}", f"token-{bot_id}", webhook_url, enabled)
    return platform_app.db.get_bot(bot_id), {"Authorization": f"Bearer token-{bot_id}"}


def make_invite(bot_id=DEFAULT_BOT, max_uses=1, expires_at=None, code=None):
    code = code or platform_app.new_invite_code()
    platform_app.db.create_invite(code, bot_id, None, max_uses, expires_at)
    return code
