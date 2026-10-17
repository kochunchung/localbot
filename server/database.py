"""
SQLite database manager for LocalBot server.

多 Bot：一個平台可以有多個 Bot（bots），使用者（users）透過邀請碼加入 Bot 成為它的好友（memberships）。
訊息、reply token、Rich Menu、排程、Webhook 日誌都屬於某一個 Bot（bot_id）。
"""
import sqlite3
import json
import time
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Any, Dict, List, Optional


def _like(value: str) -> str:
    """把使用者輸入轉成安全的 LIKE 樣式（配合 ESCAPE '\\'）。"""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


DEFAULT_BOT_ID = "default"  # 從舊版（單一 Bot）升級時，既有資料都歸到這個 Bot


class Database:
    def __init__(self, db_path: str = "localbot.db"):
        self.db_path = db_path
        self._init_tables()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 資料表
    # ------------------------------------------------------------------
    @staticmethod
    def _columns(cursor, table: str) -> set:
        return {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}

    def _add_column(self, cursor, table: str, column: str, ddl: str) -> None:
        cols = self._columns(cursor, table)
        if cols and column not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _scoped_table(self, cursor, name: str, create_sql: str, copy_sql: str) -> None:
        """建立「以 bot_id 分開」的資料表；舊版（沒有 bot_id）的資料表先改名、重建、複製資料。"""
        cols = self._columns(cursor, name)
        if cols and "bot_id" not in cols:
            cursor.execute(f"ALTER TABLE {name} RENAME TO {name}_old")
            cursor.execute(create_sql)
            cursor.execute(copy_sql.format(old=f"{name}_old"))
            cursor.execute(f"DROP TABLE {name}_old")
        else:
            cursor.execute(create_sql)

    def _init_tables(self):
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    device_secret TEXT NOT NULL DEFAULT '-',
                    display_name TEXT,
                    created_at INTEGER NOT NULL,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    token_hash TEXT,
                    revoked_at INTEGER,
                    last_seen_at INTEGER
                )
            """)
            self._add_column(c, "users", "blocked", "INTEGER NOT NULL DEFAULT 0")
            self._add_column(c, "users", "token_hash", "TEXT")
            self._add_column(c, "users", "revoked_at", "INTEGER")
            self._add_column(c, "users", "last_seen_at", "INTEGER")

            c.execute("""
                CREATE TABLE IF NOT EXISTS bots (
                    bot_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    channel_secret TEXT NOT NULL,
                    channel_access_token TEXT NOT NULL,
                    webhook_url TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    avatar TEXT
                )
            """)
            self._add_column(c, "bots", "avatar", "TEXT")  # 3.1：頭像檔名（media/avatars/ 底下）
            c.execute("""
                CREATE TABLE IF NOT EXISTS memberships (
                    bot_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    joined_at INTEGER NOT NULL,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (bot_id, user_id)
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_memberships_user ON memberships(user_id)")
            c.execute("""
                CREATE TABLE IF NOT EXISTS invites (
                    code TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    label TEXT,
                    max_uses INTEGER NOT NULL DEFAULT 1,
                    uses INTEGER NOT NULL DEFAULT 0,
                    expires_at INTEGER,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS reply_tokens (
                    reply_token TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            self._add_column(c, "reply_tokens", "bot_id", "TEXT NOT NULL DEFAULT 'default'")
            c.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL DEFAULT 'default',
                    message_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            self._add_column(c, "messages", "bot_id", "TEXT NOT NULL DEFAULT 'default'")
            c.execute("""
                CREATE TABLE IF NOT EXISTS offline_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT,
                    user_id TEXT NOT NULL,
                    message_data TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            self._add_column(c, "offline_queue", "bot_id", "TEXT")
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_bot_user ON messages(bot_id, user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_offline_user ON offline_queue(user_id)")
            # Rich Menu（每個 Bot 各自的選單、別名、使用者綁定）
            c.execute("""
                CREATE TABLE IF NOT EXISTS richmenus (
                    richmenu_id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL DEFAULT 'default',
                    data TEXT NOT NULL,
                    image_ext TEXT,
                    created_at INTEGER NOT NULL
                )
            """)
            self._add_column(c, "richmenus", "bot_id", "TEXT NOT NULL DEFAULT 'default'")
            self._scoped_table(c, "richmenu_aliases", """
                CREATE TABLE IF NOT EXISTS richmenu_aliases (
                    bot_id TEXT NOT NULL,
                    alias_id TEXT NOT NULL,
                    richmenu_id TEXT NOT NULL,
                    PRIMARY KEY (bot_id, alias_id)
                )
            """, "INSERT INTO richmenu_aliases (bot_id, alias_id, richmenu_id) "
                 "SELECT 'default', alias_id, richmenu_id FROM {old}")
            self._scoped_table(c, "user_richmenus", """
                CREATE TABLE IF NOT EXISTS user_richmenus (
                    bot_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    richmenu_id TEXT NOT NULL,
                    PRIMARY KEY (bot_id, user_id)
                )
            """, "INSERT INTO user_richmenus (bot_id, user_id, richmenu_id) "
                 "SELECT 'default', user_id, richmenu_id FROM {old}")
            c.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            # Webhook 轉送紀錄與重試
            c.execute("""
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT,
                    event_type TEXT,
                    event_id TEXT,
                    event_count INTEGER NOT NULL DEFAULT 1,
                    body TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_status INTEGER,
                    last_error TEXT,
                    next_attempt_at INTEGER,
                    manual_pending INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            self._add_column(c, "webhook_deliveries", "bot_id", "TEXT NOT NULL DEFAULT 'default'")
            c.execute("""
                CREATE TABLE IF NOT EXISTS webhook_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    delivery_id INTEGER NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    manual INTEGER NOT NULL DEFAULT 0,
                    ok INTEGER NOT NULL,
                    status_code INTEGER,
                    error TEXT,
                    duration_ms INTEGER,
                    created_at INTEGER NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_wd_state_next ON webhook_deliveries(state, next_attempt_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_wd_created ON webhook_deliveries(created_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_wa_delivery ON webhook_attempts(delivery_id)")
            # 排程推播
            c.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_pushes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL DEFAULT 'default',
                    name TEXT NOT NULL,
                    messages TEXT NOT NULL,
                    target TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    next_run_at INTEGER,
                    last_run_at INTEGER,
                    last_result TEXT,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            self._add_column(c, "scheduled_pushes", "bot_id", "TEXT NOT NULL DEFAULT 'default'")
            c.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_push_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    sent INTEGER NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at INTEGER NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_sp_next ON scheduled_pushes(enabled, next_run_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_spr_schedule ON scheduled_push_runs(schedule_id, id)")

            # 從單一 Bot 的舊版升級：既有使用者都成為「預設 Bot」的好友（只做一次）
            if c.execute("SELECT 1 FROM settings WHERE key = 'multibot_migrated'").fetchone() is None:
                c.execute("INSERT OR IGNORE INTO memberships (bot_id, user_id, joined_at, blocked) "
                          "SELECT ?, user_id, created_at, blocked FROM users", (DEFAULT_BOT_ID,))
                c.execute("UPDATE settings SET key = ? WHERE key = 'default_richmenu'",
                          (f"default_richmenu:{DEFAULT_BOT_ID}",))
                c.execute("INSERT INTO settings (key, value) VALUES ('multibot_migrated', '1')")
            conn.commit()

    # ------------------------------------------------------------------
    # Bots
    # ------------------------------------------------------------------
    def create_bot(self, bot_id: str, name: str, description: Optional[str], channel_secret: str,
                   channel_access_token: str, webhook_url: str, enabled: bool = True) -> None:
        now = int(time.time() * 1000)
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO bots (bot_id, name, description, channel_secret, channel_access_token, webhook_url, "
                "enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (bot_id, name, description, channel_secret, channel_access_token, webhook_url,
                 1 if enabled else 0, now, now))
            conn.commit()

    @staticmethod
    def _bot_row(row) -> Dict[str, Any]:
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        return d

    def get_bot(self, bot_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM bots WHERE bot_id = ?", (bot_id,)).fetchone()
            return self._bot_row(row) if row else None

    def list_bots(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            sql = "SELECT * FROM bots " + ("WHERE enabled = 1 " if enabled_only else "") + "ORDER BY created_at ASC, bot_id ASC"
            return [self._bot_row(r) for r in conn.execute(sql).fetchall()]

    _BOT_FIELDS = ("name", "description", "channel_secret", "channel_access_token", "webhook_url", "enabled", "avatar")

    def update_bot(self, bot_id: str, **fields) -> bool:
        sets, params = [], []
        for key, value in fields.items():
            if key not in self._BOT_FIELDS:
                raise KeyError(key)
            sets.append(f"{key} = ?")
            params.append((1 if value else 0) if key == "enabled" else value)
        if not sets:
            return self.get_bot(bot_id) is not None
        sets.append("updated_at = ?")
        params += [int(time.time() * 1000), bot_id]
        with self._get_connection() as conn:
            cur = conn.execute(f"UPDATE bots SET {', '.join(sets)} WHERE bot_id = ?", params)
            conn.commit()
            return cur.rowcount > 0

    def delete_bot(self, bot_id: str) -> List[Dict[str, Any]]:
        """刪除 Bot 與它所有的資料。回傳它的 Rich Menu 圖片（供呼叫端刪檔）。"""
        with self._get_connection() as conn:
            menus = [{"richMenuId": r["richmenu_id"], "imageExt": r["image_ext"]} for r in conn.execute(
                "SELECT richmenu_id, image_ext FROM richmenus WHERE bot_id = ?", (bot_id,)).fetchall()]
            conn.execute("DELETE FROM scheduled_push_runs WHERE schedule_id IN "
                         "(SELECT id FROM scheduled_pushes WHERE bot_id = ?)", (bot_id,))
            conn.execute("DELETE FROM webhook_attempts WHERE delivery_id IN "
                         "(SELECT id FROM webhook_deliveries WHERE bot_id = ?)", (bot_id,))
            for table in ("scheduled_pushes", "webhook_deliveries", "invites", "richmenu_aliases", "user_richmenus",
                          "richmenus", "reply_tokens", "offline_queue", "messages", "memberships", "bots"):
                conn.execute(f"DELETE FROM {table} WHERE bot_id = ?", (bot_id,))
            conn.execute("DELETE FROM settings WHERE key = ?", (f"default_richmenu:{bot_id}",))
            conn.commit()
        return menus

    def bot_member_counts(self) -> Dict[str, Dict[str, int]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT bot_id, COUNT(*) AS n, COALESCE(SUM(blocked), 0) AS b "
                                "FROM memberships GROUP BY bot_id").fetchall()
        return {r["bot_id"]: {"members": r["n"], "blocked": r["b"]} for r in rows}

    # ------------------------------------------------------------------
    # 使用者（裝置）與金鑰
    #   token_hash：使用者金鑰的 SHA-256；NULL = 尚未發金鑰或已被撤銷，必須用邀請碼重新加入。
    # ------------------------------------------------------------------
    def create_user(self, user_id: str, display_name: Optional[str] = None, token_hash: Optional[str] = None) -> bool:
        """建立使用者；已存在則回傳 False（不修改）。"""
        now = int(time.time() * 1000)
        with self._get_connection() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO users (user_id, device_secret, display_name, created_at, token_hash) "
                "VALUES (?, '-', ?, ?, ?)", (user_id, display_name or "User", now, token_hash))
            conn.commit()
            return cur.rowcount == 1

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def set_user_token(self, user_id: str, token_hash: str) -> bool:
        """發新金鑰（同時解除撤銷狀態）。"""
        with self._get_connection() as conn:
            cur = conn.execute("UPDATE users SET token_hash = ?, revoked_at = NULL WHERE user_id = ?",
                               (token_hash, user_id))
            conn.commit()
            return cur.rowcount > 0

    def revoke_user_token(self, user_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("UPDATE users SET token_hash = NULL, revoked_at = ? WHERE user_id = ?",
                               (int(time.time() * 1000), user_id))
            conn.commit()
            return cur.rowcount > 0

    def get_token_hash(self, user_id: str) -> Optional[str]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT token_hash FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row["token_hash"] if row else None

    def touch_user(self, user_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("UPDATE users SET last_seen_at = ? WHERE user_id = ?", (int(time.time() * 1000), user_id))
            conn.commit()

    def update_display_name(self, user_id: str, display_name: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("UPDATE users SET display_name = ? WHERE user_id = ?", (display_name, user_id))
            conn.commit()
            return cur.rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        """刪除使用者與其所有資料（所有 Bot 的訊息、離線佇列、reply token、Rich Menu 綁定、好友關係）。"""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            for table in ("messages", "offline_queue", "reply_tokens", "user_richmenus", "memberships"):
                conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # 好友關係（使用者 × Bot）
    # ------------------------------------------------------------------
    def add_membership(self, bot_id: str, user_id: str) -> bool:
        """加入 Bot；已經是好友則回傳 False。"""
        with self._get_connection() as conn:
            cur = conn.execute("INSERT OR IGNORE INTO memberships (bot_id, user_id, joined_at, blocked) "
                               "VALUES (?, ?, ?, 0)", (bot_id, user_id, int(time.time() * 1000)))
            conn.commit()
            return cur.rowcount == 1

    def get_membership(self, bot_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM memberships WHERE bot_id = ? AND user_id = ?", (bot_id, user_id)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["blocked"] = bool(d["blocked"])
            return d

    def is_member(self, bot_id: str, user_id: str) -> bool:
        return self.get_membership(bot_id, user_id) is not None

    def list_memberships(self, user_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT m.bot_id, m.joined_at, m.blocked, b.name, b.description, b.enabled, b.avatar, "
                "(SELECT MAX(x.created_at) FROM messages x WHERE x.bot_id = m.bot_id AND x.user_id = m.user_id) AS last_message_at "
                "FROM memberships m LEFT JOIN bots b ON b.bot_id = m.bot_id WHERE m.user_id = ? "
                "ORDER BY m.joined_at ASC", (user_id,)).fetchall()
        return [{"bot_id": r["bot_id"], "joined_at": r["joined_at"], "blocked": bool(r["blocked"]),
                 "name": r["name"], "description": r["description"], "avatar": r["avatar"],
                 "enabled": bool(r["enabled"]) if r["enabled"] is not None else False,
                 "last_message_at": r["last_message_at"]} for r in rows]

    def list_user_ids(self, bot_id: str, include_blocked: bool = False) -> List[str]:
        """這個 Bot 的好友 ID（供 broadcast 使用），預設排除已封鎖的使用者。"""
        with self._get_connection() as conn:
            sql = "SELECT user_id FROM memberships WHERE bot_id = ?"
            if not include_blocked:
                sql += " AND blocked = 0"
            return [r["user_id"] for r in conn.execute(sql + " ORDER BY joined_at ASC", (bot_id,)).fetchall()]

    def set_blocked(self, bot_id: str, user_id: str, blocked: bool) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("UPDATE memberships SET blocked = ? WHERE bot_id = ? AND user_id = ?",
                               (1 if blocked else 0, bot_id, user_id))
            conn.commit()
            return cur.rowcount > 0

    def is_blocked(self, bot_id: str, user_id: str) -> bool:
        """不是好友（或已封鎖）都視為不能收到訊息，由呼叫端先用 is_member 區分。"""
        m = self.get_membership(bot_id, user_id)
        return bool(m and m["blocked"])

    def remove_membership(self, bot_id: str, user_id: str) -> bool:
        """刪除好友：移除關係與這個 Bot 與使用者之間的所有資料。"""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM memberships WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
            for table in ("messages", "offline_queue", "reply_tokens", "user_richmenus"):
                conn.execute(f"DELETE FROM {table} WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # 邀請碼
    # ------------------------------------------------------------------
    def create_invite(self, code: str, bot_id: str, label: Optional[str], max_uses: int,
                      expires_at: Optional[int]) -> None:
        with self._get_connection() as conn:
            conn.execute("INSERT INTO invites (code, bot_id, label, max_uses, uses, expires_at, revoked, created_at) "
                         "VALUES (?, ?, ?, ?, 0, ?, 0, ?)",
                         (code, bot_id, label, max_uses, expires_at, int(time.time() * 1000)))
            conn.commit()

    def get_invite(self, code: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM invites WHERE code = ?", (code,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["revoked"] = bool(d["revoked"])
            return d

    def list_invites(self, bot_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if bot_id:
                rows = conn.execute("SELECT * FROM invites WHERE bot_id = ? ORDER BY created_at DESC", (bot_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM invites ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["revoked"] = bool(d["revoked"])
            out.append(d)
        return out

    def revoke_invite(self, code: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("UPDATE invites SET revoked = 1 WHERE code = ?", (code,))
            conn.commit()
            return cur.rowcount > 0

    def delete_invite(self, code: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM invites WHERE code = ?", (code,))
            conn.commit()
            return cur.rowcount > 0

    def consume_invite(self, code: str, now_ms: Optional[int] = None) -> bool:
        """使用一次邀請碼（原子操作）：已撤銷、過期或用完都會失敗。"""
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE invites SET uses = uses + 1 WHERE code = ? AND revoked = 0 AND uses < max_uses "
                "AND (expires_at IS NULL OR expires_at > ?)", (code, now))
            conn.commit()
            return cur.rowcount == 1

    def refund_invite(self, code: str) -> None:
        """加入失敗時把剛用掉的次數還回去。"""
        with self._get_connection() as conn:
            conn.execute("UPDATE invites SET uses = MAX(uses - 1, 0) WHERE code = ?", (code,))
            conn.commit()

    # ------------------------------------------------------------------
    # reply token / 訊息 / 離線佇列
    # ------------------------------------------------------------------
    def save_reply_token(self, bot_id: str, reply_token: str, user_id: str):
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO reply_tokens (reply_token, bot_id, user_id, created_at) "
                         "VALUES (?, ?, ?, ?)", (reply_token, bot_id, user_id, int(time.time() * 1000)))
            conn.commit()

    def get_user_by_reply_token(self, bot_id: str, reply_token: str) -> Optional[str]:
        """reply token 只能由發出它的 Bot 使用。"""
        with self._get_connection() as conn:
            row = conn.execute("SELECT user_id FROM reply_tokens WHERE reply_token = ? AND bot_id = ?",
                               (reply_token, bot_id)).fetchone()
            return row["user_id"] if row else None

    def save_message(self, bot_id: str, message_id: str, user_id: str, direction: str, message_type: str, content: Any):
        now = int(time.time() * 1000)
        content_str = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content
        with self._get_connection() as conn:
            conn.execute("INSERT INTO messages (bot_id, message_id, user_id, direction, message_type, content, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", (bot_id, message_id, user_id, direction, message_type, content_str, now))
            conn.commit()

    def get_messages(self, bot_id: str, user_id: str, limit: int = 50, before_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if before_id:
                rows = conn.execute("SELECT * FROM messages WHERE bot_id = ? AND user_id = ? AND id < ? "
                                    "ORDER BY id DESC LIMIT ?", (bot_id, user_id, before_id, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM messages WHERE bot_id = ? AND user_id = ? "
                                    "ORDER BY id DESC LIMIT ?", (bot_id, user_id, limit)).fetchall()
        messages = []
        for row in reversed(rows):
            d = dict(row)
            try:
                d["content"] = json.loads(d["content"])
            except Exception:
                pass
            messages.append(d)
        return messages

    def has_message(self, bot_id: str, message_id: str) -> bool:
        with self._get_connection() as conn:
            return conn.execute("SELECT 1 FROM messages WHERE bot_id = ? AND message_id = ? LIMIT 1",
                                (bot_id, message_id)).fetchone() is not None

    def enqueue_offline_message(self, bot_id: str, user_id: str, message_data: Any):
        data_str = json.dumps(message_data, ensure_ascii=False) if not isinstance(message_data, str) else message_data
        with self._get_connection() as conn:
            conn.execute("INSERT INTO offline_queue (bot_id, user_id, message_data, created_at) VALUES (?, ?, ?, ?)",
                         (bot_id, user_id, data_str, int(time.time() * 1000)))
            conn.commit()

    def pop_offline_messages(self, user_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT id, message_data FROM offline_queue WHERE user_id = ? ORDER BY id ASC",
                                (user_id,)).fetchall()
            if not rows:
                return []
            ids = [row["id"] for row in rows]
            messages = []
            for row in rows:
                try:
                    messages.append(json.loads(row["message_data"]))
                except Exception:
                    messages.append(row["message_data"])
            conn.execute(f"DELETE FROM offline_queue WHERE id IN ({','.join(['?'] * len(ids))})", ids)
            conn.commit()
            return messages

    # ------------------------------------------------------------------
    # Rich Menu（皆以 bot_id 分開）
    # ------------------------------------------------------------------
    def create_richmenu(self, bot_id: str, richmenu_id: str, data: Dict[str, Any]) -> None:
        with self._get_connection() as conn:
            conn.execute("INSERT INTO richmenus (richmenu_id, bot_id, data, image_ext, created_at) VALUES (?, ?, ?, NULL, ?)",
                         (richmenu_id, bot_id, json.dumps(data, ensure_ascii=False), int(time.time() * 1000)))
            conn.commit()

    @staticmethod
    def _menu(row) -> Dict[str, Any]:
        return {"richMenuId": row["richmenu_id"], "botId": row["bot_id"], "imageExt": row["image_ext"], **json.loads(row["data"])}

    def get_richmenu(self, bot_id: str, richmenu_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM richmenus WHERE richmenu_id = ? AND bot_id = ?", (richmenu_id, bot_id)).fetchone()
            return self._menu(row) if row else None

    def get_richmenu_any(self, richmenu_id: str) -> Optional[Dict[str, Any]]:
        """不限 Bot（App 取圖片用；選單 ID 是不可猜的亂數）。"""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM richmenus WHERE richmenu_id = ?", (richmenu_id,)).fetchone()
            return self._menu(row) if row else None

    def list_richmenus(self, bot_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM richmenus WHERE bot_id = ? ORDER BY created_at ASC", (bot_id,)).fetchall()
            return [self._menu(r) for r in rows]

    def set_richmenu_image(self, richmenu_id: str, ext: str) -> None:
        with self._get_connection() as conn:
            conn.execute("UPDATE richmenus SET image_ext = ? WHERE richmenu_id = ?", (ext, richmenu_id))
            conn.commit()

    def delete_richmenu(self, bot_id: str, richmenu_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM richmenus WHERE richmenu_id = ? AND bot_id = ?", (richmenu_id, bot_id))
            conn.execute("DELETE FROM richmenu_aliases WHERE richmenu_id = ? AND bot_id = ?", (richmenu_id, bot_id))
            conn.execute("DELETE FROM user_richmenus WHERE richmenu_id = ? AND bot_id = ?", (richmenu_id, bot_id))
            conn.execute("DELETE FROM settings WHERE key = ? AND value = ?", (f"default_richmenu:{bot_id}", richmenu_id))
            conn.commit()

    def link_richmenu(self, bot_id: str, user_id: str, richmenu_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO user_richmenus (bot_id, user_id, richmenu_id) VALUES (?, ?, ?)",
                         (bot_id, user_id, richmenu_id))
            conn.commit()

    def unlink_richmenu(self, bot_id: str, user_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM user_richmenus WHERE bot_id = ? AND user_id = ?", (bot_id, user_id))
            conn.commit()

    def get_user_richmenu_id(self, bot_id: str, user_id: str) -> Optional[str]:
        """使用者個別綁定的 Rich Menu（不含預設）。"""
        with self._get_connection() as conn:
            row = conn.execute("SELECT richmenu_id FROM user_richmenus WHERE bot_id = ? AND user_id = ?",
                               (bot_id, user_id)).fetchone()
            return row["richmenu_id"] if row else None

    def users_with_richmenu(self, bot_id: str, richmenu_id: str) -> List[str]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT user_id FROM user_richmenus WHERE bot_id = ? AND richmenu_id = ?",
                                (bot_id, richmenu_id)).fetchall()
            return [r["user_id"] for r in rows]

    def get_setting(self, key: str) -> Optional[str]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_setting(self, key: str, value: Optional[str]) -> None:
        with self._get_connection() as conn:
            if value is None:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()

    def set_richmenu_alias(self, bot_id: str, alias_id: str, richmenu_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO richmenu_aliases (bot_id, alias_id, richmenu_id) VALUES (?, ?, ?)",
                         (bot_id, alias_id, richmenu_id))
            conn.commit()

    def get_richmenu_alias(self, bot_id: str, alias_id: str) -> Optional[str]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT richmenu_id FROM richmenu_aliases WHERE bot_id = ? AND alias_id = ?",
                               (bot_id, alias_id)).fetchone()
            return row["richmenu_id"] if row else None

    def delete_richmenu_alias(self, bot_id: str, alias_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM richmenu_aliases WHERE bot_id = ? AND alias_id = ?", (bot_id, alias_id))
            conn.commit()
            return cur.rowcount > 0

    def list_richmenu_aliases(self, bot_id: str) -> List[Dict[str, str]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT alias_id, richmenu_id FROM richmenu_aliases WHERE bot_id = ? ORDER BY alias_id",
                                (bot_id,)).fetchall()
            return [{"richMenuAliasId": r["alias_id"], "richMenuId": r["richmenu_id"]} for r in rows]

    # ------------------------------------------------------------------
    # 管理後台：統計、使用者、訊息查詢
    # ------------------------------------------------------------------
    def stats(self, bot_id: Optional[str] = None) -> Dict[str, Any]:
        now = int(time.time() * 1000)
        bw = " WHERE bot_id = ?" if bot_id else ""
        bp = [bot_id] if bot_id else []
        with self._get_connection() as conn:
            if bot_id:
                u = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(blocked), 0) AS b FROM memberships WHERE bot_id = ?",
                                 bp).fetchone()
                users, blocked = u["n"], u["b"]
            else:
                users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
                blocked = conn.execute("SELECT COALESCE(SUM(blocked), 0) AS b FROM memberships").fetchone()["b"]
            by_dir = {r["direction"]: r["n"] for r in conn.execute(
                f"SELECT direction, COUNT(*) AS n FROM messages{bw} GROUP BY direction", bp).fetchall()}
            last24 = conn.execute("SELECT COUNT(*) AS n FROM messages WHERE created_at >= ?"
                                  + (" AND bot_id = ?" if bot_id else ""), [now - 24 * 3600 * 1000] + bp).fetchone()["n"]
            offline = conn.execute(f"SELECT COUNT(*) AS n FROM offline_queue{bw}", bp).fetchone()["n"]
            menus = conn.execute(f"SELECT COUNT(*) AS n FROM richmenus{bw}", bp).fetchone()["n"]
            bots = conn.execute("SELECT COUNT(*) AS n FROM bots").fetchone()["n"]
        return {
            "users": users, "blockedUsers": blocked, "bots": bots,
            "messagesIncoming": by_dir.get("incoming", 0),
            "messagesOutgoing": by_dir.get("outgoing", 0),
            "messagesLast24h": last24,
            "offlineQueue": offline,
            "richMenus": menus,
        }

    def message_counts_by_day(self, days: int = 7, bot_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """最近 N 天（含今天，伺服器本地時區）每天收到 / 送出的訊息數。"""
        today = datetime.now().date()
        start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
        since_ms = int(start.timestamp() * 1000)
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT strftime('%Y-%m-%d', created_at / 1000, 'unixepoch', 'localtime') AS d, direction, COUNT(*) AS n "
                "FROM messages WHERE created_at >= ?" + (" AND bot_id = ?" if bot_id else "") + " GROUP BY d, direction",
                [since_ms] + ([bot_id] if bot_id else [])).fetchall()
        table = {(r["d"], r["direction"]): r["n"] for r in rows}
        result = []
        for i in range(days):
            day = (today - timedelta(days=days - 1 - i)).isoformat()
            result.append({"date": day,
                           "incoming": table.get((day, "incoming"), 0),
                           "outgoing": table.get((day, "outgoing"), 0)})
        return result

    def list_users(self, q: Optional[str] = None, limit: int = 50, offset: int = 0,
                   bot_id: Optional[str] = None) -> Dict[str, Any]:
        where, params = [], []
        if q:
            where.append("(u.user_id LIKE ? ESCAPE '\\' OR u.display_name LIKE ? ESCAPE '\\')")
            params += [_like(q), _like(q)]
        if bot_id:
            where.append("EXISTS (SELECT 1 FROM memberships mm WHERE mm.user_id = u.user_id AND mm.bot_id = ?)")
            params.append(bot_id)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        scope = " AND m.bot_id = ?" if bot_id else ""
        sp = [bot_id] if bot_id else []
        with self._get_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM users u {clause}", params).fetchone()["n"]
            rows = conn.execute(f"""
                SELECT u.user_id, u.display_name, u.created_at, u.token_hash IS NOT NULL AS has_key,
                    u.revoked_at, u.last_seen_at,
                    (SELECT COUNT(*) FROM messages m WHERE m.user_id = u.user_id{scope}) AS message_count,
                    (SELECT MAX(m.created_at) FROM messages m WHERE m.user_id = u.user_id{scope}) AS last_message_at
                FROM users u {clause}
                ORDER BY u.created_at DESC LIMIT ? OFFSET ?
            """, sp + sp + params + [limit, offset]).fetchall()
            users = [dict(r) for r in rows]
            if users:
                ids = [u["user_id"] for u in users]
                marks = ",".join("?" * len(ids))
                mem = conn.execute(
                    f"SELECT m.user_id, m.bot_id, m.blocked, b.name FROM memberships m "
                    f"LEFT JOIN bots b ON b.bot_id = m.bot_id WHERE m.user_id IN ({marks}) ORDER BY m.joined_at", ids).fetchall()
                by_user: Dict[str, list] = {}
                for r in mem:
                    by_user.setdefault(r["user_id"], []).append(
                        {"botId": r["bot_id"], "botName": r["name"], "blocked": bool(r["blocked"])})
                for u in users:
                    u["has_key"] = bool(u["has_key"])
                    u["bots"] = by_user.get(u["user_id"], [])
        return {"total": total, "users": users}

    def search_messages(self, q: Optional[str] = None, direction: Optional[str] = None,
                        message_type: Optional[str] = None, user: Optional[str] = None,
                        user_id: Optional[str] = None, bot_id: Optional[str] = None,
                        limit: int = 50, before_id: Optional[int] = None) -> Dict[str, Any]:
        """搜尋訊息（新到舊）。user 為 ID / 名稱模糊比對，user_id 為精確比對。回傳 {messages, hasMore}。"""
        where, params = [], []
        if q:
            where.append("m.content LIKE ? ESCAPE '\\'")
            params.append(_like(q))
        if direction in ("incoming", "outgoing"):
            where.append("m.direction = ?")
            params.append(direction)
        if message_type:
            where.append("m.message_type = ?")
            params.append(message_type)
        if user_id:
            where.append("m.user_id = ?")
            params.append(user_id)
        if bot_id:
            where.append("m.bot_id = ?")
            params.append(bot_id)
        if user:
            where.append("(m.user_id LIKE ? ESCAPE '\\' OR u.display_name LIKE ? ESCAPE '\\')")
            params += [_like(user), _like(user)]
        if before_id:
            where.append("m.id < ?")
            params.append(before_id)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        with self._get_connection() as conn:
            rows = conn.execute(f"""
                SELECT m.*, u.display_name, b.name AS bot_name FROM messages m
                LEFT JOIN users u ON u.user_id = m.user_id
                LEFT JOIN bots b ON b.bot_id = m.bot_id
                {clause} ORDER BY m.id DESC LIMIT ?
            """, params + [limit + 1]).fetchall()
        has_more = len(rows) > limit
        messages = []
        for row in rows[:limit]:
            d = dict(row)
            try:
                d["content"] = json.loads(d["content"])
            except Exception:
                pass
            messages.append(d)
        return {"messages": messages, "hasMore": has_more}

    # ------------------------------------------------------------------
    # Webhook 轉送紀錄 / 重試
    #   state: sending（嘗試中）→ success | retrying（等待重試）| dead（放棄，可手動重送）
    # ------------------------------------------------------------------
    def create_delivery(self, bot_id: str, user_id: Optional[str], event_type: Optional[str], event_id: Optional[str],
                        body: str, event_count: int = 1) -> int:
        now = int(time.time() * 1000)
        with self._get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO webhook_deliveries (bot_id, user_id, event_type, event_id, event_count, body, state, attempts, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'sending', 0, ?, ?)",
                (bot_id, user_id, event_type, event_id, event_count, body, now, now))
            conn.commit()
            return cur.lastrowid

    def get_delivery(self, delivery_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM webhook_deliveries WHERE id = ?", (delivery_id,)).fetchone()
            return dict(row) if row else None

    def claim_delivery(self, delivery_id: int, now_ms: Optional[int] = None, only_due: bool = True) -> bool:
        """搶占一筆轉送準備嘗試（避免重複處理）。only_due=True 只搶「到期的 retrying」；否則任何非 sending 的都可（手動重送）。"""
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        with self._get_connection() as conn:
            if only_due:
                cur = conn.execute(
                    "UPDATE webhook_deliveries SET state = 'sending', next_attempt_at = NULL, updated_at = ? "
                    "WHERE id = ? AND state = 'retrying' AND next_attempt_at <= ?", (now, delivery_id, now))
            else:
                cur = conn.execute(
                    "UPDATE webhook_deliveries SET state = 'sending', next_attempt_at = NULL, manual_pending = 1, "
                    "updated_at = ? WHERE id = ? AND state != 'sending'", (now, delivery_id))
            conn.commit()
            return cur.rowcount == 1

    def due_deliveries(self, now_ms: Optional[int] = None, limit: int = 5) -> List[int]:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM webhook_deliveries WHERE state = 'retrying' AND next_attempt_at <= ? "
                "ORDER BY next_attempt_at ASC LIMIT ?", (now, limit)).fetchall()
            return [r["id"] for r in rows]

    def record_attempt(self, delivery_id: int, ok: bool, status_code: Optional[int], error: Optional[str],
                       duration_ms: int, manual: bool, new_state: str, next_attempt_at: Optional[int]) -> None:
        """記錄一次嘗試並更新轉送狀態（同一個交易）。"""
        now = int(time.time() * 1000)
        with self._get_connection() as conn:
            attempts = conn.execute("SELECT attempts FROM webhook_deliveries WHERE id = ?", (delivery_id,)).fetchone()
            n = (attempts["attempts"] if attempts else 0) + 1
            conn.execute(
                "INSERT INTO webhook_attempts (delivery_id, attempt_no, manual, ok, status_code, error, duration_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (delivery_id, n, 1 if manual else 0, 1 if ok else 0, status_code, error, duration_ms, now))
            conn.execute(
                "UPDATE webhook_deliveries SET state = ?, attempts = ?, last_status = ?, last_error = ?, "
                "next_attempt_at = ?, manual_pending = 0, updated_at = ? WHERE id = ?",
                (new_state, n, status_code, error, next_attempt_at, now, delivery_id))
            conn.commit()

    def count_auto_attempts(self, delivery_id: int) -> int:
        with self._get_connection() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM webhook_attempts WHERE delivery_id = ? AND manual = 0",
                                (delivery_id,)).fetchone()["n"]

    def list_attempts(self, delivery_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM webhook_attempts WHERE delivery_id = ? ORDER BY id ASC",
                                (delivery_id,)).fetchall()
            return [dict(r) for r in rows]

    def list_deliveries(self, state: Optional[str] = None, q: Optional[str] = None,
                        limit: int = 50, before_id: Optional[int] = None,
                        bot_id: Optional[str] = None) -> Dict[str, Any]:
        where, params = [], []
        if bot_id:
            where.append("bot_id = ?")
            params.append(bot_id)
        if state in ("sending", "retrying", "success", "dead"):
            where.append("state = ?")
            params.append(state)
        if q:
            where.append("(user_id LIKE ? ESCAPE '\\' OR event_type LIKE ? ESCAPE '\\' OR event_id LIKE ? ESCAPE '\\')")
            params += [_like(q)] * 3
        if before_id:
            where.append("id < ?")
            params.append(before_id)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, bot_id, user_id, event_type, event_id, event_count, state, attempts, last_status, last_error, "
                f"next_attempt_at, created_at, updated_at FROM webhook_deliveries {clause} ORDER BY id DESC LIMIT ?",
                params + [limit + 1]).fetchall()
        return {"deliveries": [dict(r) for r in rows[:limit]], "hasMore": len(rows) > limit}

    def delivery_counts(self, bot_id: Optional[str] = None) -> Dict[str, int]:
        counts = {"sending": 0, "retrying": 0, "success": 0, "dead": 0}
        with self._get_connection() as conn:
            if bot_id:
                rows = conn.execute("SELECT state, COUNT(*) AS n FROM webhook_deliveries WHERE bot_id = ? GROUP BY state",
                                    (bot_id,)).fetchall()
            else:
                rows = conn.execute("SELECT state, COUNT(*) AS n FROM webhook_deliveries GROUP BY state").fetchall()
            for r in rows:
                counts[r["state"]] = r["n"]
        return counts

    def requeue_dead(self, now_ms: Optional[int] = None, limit: int = 100) -> int:
        """把放棄的轉送全部排回重試佇列（由背景工作逐一處理）。回傳筆數。"""
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE webhook_deliveries SET state = 'retrying', next_attempt_at = ?, manual_pending = 1, updated_at = ? WHERE id IN "
                "(SELECT id FROM webhook_deliveries WHERE state = 'dead' ORDER BY id DESC LIMIT ?)", (now, now, limit))
            conn.commit()
            return cur.rowcount

    def recover_sending(self, now_ms: Optional[int] = None) -> int:
        """伺服器啟動時：上次嘗試到一半被中斷的轉送，排回重試。"""
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE webhook_deliveries SET state = 'retrying', next_attempt_at = ?, updated_at = ? "
                "WHERE state = 'sending'", (now, now))
            conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------
    # 排程推播
    # ------------------------------------------------------------------
    @staticmethod
    def _schedule_row(row) -> Dict[str, Any]:
        d = dict(row)
        for key in ("messages", "target", "schedule", "last_result"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
        d["enabled"] = bool(d["enabled"])
        return d

    def create_schedule(self, bot_id: str, name: str, messages: list, target: dict, schedule: dict,
                        enabled: bool, next_run_at: Optional[int]) -> int:
        now = int(time.time() * 1000)
        with self._get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO scheduled_pushes (bot_id, name, messages, target, schedule, enabled, next_run_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (bot_id, name, json.dumps(messages, ensure_ascii=False), json.dumps(target), json.dumps(schedule),
                 1 if enabled else 0, next_run_at, now, now))
            conn.commit()
            return cur.lastrowid

    def update_schedule(self, schedule_id: int, bot_id: str, name: str, messages: list, target: dict, schedule: dict,
                        enabled: bool, next_run_at: Optional[int]) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE scheduled_pushes SET bot_id = ?, name = ?, messages = ?, target = ?, schedule = ?, enabled = ?, "
                "next_run_at = ?, updated_at = ? WHERE id = ?",
                (bot_id, name, json.dumps(messages, ensure_ascii=False), json.dumps(target), json.dumps(schedule),
                 1 if enabled else 0, next_run_at, int(time.time() * 1000), schedule_id))
            conn.commit()
            return cur.rowcount > 0

    def set_schedule_enabled(self, schedule_id: int, enabled: bool, next_run_at: Optional[int]) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("UPDATE scheduled_pushes SET enabled = ?, next_run_at = ?, updated_at = ? WHERE id = ?",
                               (1 if enabled else 0, next_run_at, int(time.time() * 1000), schedule_id))
            conn.commit()
            return cur.rowcount > 0

    def get_schedule(self, schedule_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM scheduled_pushes WHERE id = ?", (schedule_id,)).fetchone()
            return self._schedule_row(row) if row else None

    def list_schedules(self, bot_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if bot_id:
                rows = conn.execute("SELECT * FROM scheduled_pushes WHERE bot_id = ? ORDER BY id DESC", (bot_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM scheduled_pushes ORDER BY id DESC").fetchall()
            return [self._schedule_row(r) for r in rows]

    def delete_schedule(self, schedule_id: int) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM scheduled_pushes WHERE id = ?", (schedule_id,))
            conn.execute("DELETE FROM scheduled_push_runs WHERE schedule_id = ?", (schedule_id,))
            conn.commit()
            return cur.rowcount > 0

    def due_schedules(self, now_ms: Optional[int] = None, limit: int = 20) -> List[Dict[str, Any]]:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_pushes WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ? "
                "ORDER BY next_run_at ASC LIMIT ?", (now, limit)).fetchall()
            return [self._schedule_row(r) for r in rows]

    def claim_schedule(self, schedule_id: int, expected_next: int, new_next: Optional[int]) -> bool:
        """比較並交換 next_run_at：只有一個執行者能搶到這次執行（先推進時間再送出 = 最多執行一次）。"""
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE scheduled_pushes SET next_run_at = ? WHERE id = ? AND enabled = 1 AND next_run_at = ?",
                (new_next, schedule_id, expected_next))
            conn.commit()
            return cur.rowcount == 1

    def record_run(self, schedule_id: int, kind: str, sent: int, skipped: int, error: Optional[str]) -> None:
        now = int(time.time() * 1000)
        result = json.dumps({"kind": kind, "sent": sent, "skipped": skipped, "error": error}, ensure_ascii=False)
        with self._get_connection() as conn:
            conn.execute("INSERT INTO scheduled_push_runs (schedule_id, kind, sent, skipped, error, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (schedule_id, kind, sent, skipped, error, now))
            if kind != "missed":
                conn.execute("UPDATE scheduled_pushes SET last_run_at = ?, last_result = ?, run_count = run_count + 1 "
                             "WHERE id = ?", (now, result, schedule_id))
            else:
                conn.execute("UPDATE scheduled_pushes SET last_result = ? WHERE id = ?", (result, schedule_id))
            # 每個排程只保留最近 50 筆執行紀錄
            conn.execute("DELETE FROM scheduled_push_runs WHERE schedule_id = ? AND id NOT IN "
                         "(SELECT id FROM scheduled_push_runs WHERE schedule_id = ? ORDER BY id DESC LIMIT 50)",
                         (schedule_id, schedule_id))
            conn.commit()

    def list_runs(self, schedule_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM scheduled_push_runs WHERE schedule_id = ? ORDER BY id DESC LIMIT ?",
                                (schedule_id, limit)).fetchall()
            return [dict(r) for r in rows]

    def automation_stats(self, bot_id: Optional[str] = None) -> Dict[str, Any]:
        counts = self.delivery_counts(bot_id)
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS n, MIN(next_run_at) AS nxt FROM scheduled_pushes "
                               "WHERE enabled = 1 AND next_run_at IS NOT NULL" + (" AND bot_id = ?" if bot_id else ""),
                               [bot_id] if bot_id else []).fetchone()
        return {"webhookRetrying": counts["retrying"], "webhookDead": counts["dead"],
                "schedulesActive": row["n"], "nextScheduleAt": row["nxt"]}

    def purge_logs(self, cutoff_ms: int) -> Dict[str, int]:
        """刪除過期的轉送紀錄（不含等待重試中的）與排程執行紀錄。"""
        with self._get_connection() as conn:
            ids = [r["id"] for r in conn.execute(
                "SELECT id FROM webhook_deliveries WHERE created_at < ? AND state IN ('success', 'dead')",
                (cutoff_ms,)).fetchall()]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                conn.execute(f"DELETE FROM webhook_attempts WHERE delivery_id IN ({marks})", chunk)
                conn.execute(f"DELETE FROM webhook_deliveries WHERE id IN ({marks})", chunk)
            runs = conn.execute("DELETE FROM scheduled_push_runs WHERE created_at < ?", (cutoff_ms,)).rowcount
            # 過期、用完或已撤銷、且建立超過保留期限的邀請碼
            invites = conn.execute(
                "DELETE FROM invites WHERE created_at < ? AND (revoked = 1 OR uses >= max_uses OR "
                "(expires_at IS NOT NULL AND expires_at < ?))", (cutoff_ms, cutoff_ms)).rowcount
            conn.commit()
        return {"deliveries": len(ids), "runs": runs, "invites": invites}
