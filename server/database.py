"""
SQLite database manager for LocalBot server.
"""
import sqlite3
import json
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional


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

    def _init_tables(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    device_secret TEXT NOT NULL,
                    display_name TEXT,
                    created_at INTEGER NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reply_tokens (
                    reply_token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS offline_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    message_data TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_offline_user ON offline_queue(user_id)")
            conn.commit()

    def register_user(self, user_id: str, device_secret: str, display_name: Optional[str] = None) -> bool:
        """Register or update a user."""
        now = int(time.time() * 1000)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (user_id, device_secret, display_name, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    device_secret = excluded.device_secret,
                    display_name = coalesce(excluded.display_name, users.display_name)
            """, (user_id, device_secret, display_name or "User", now))
            conn.commit()
            return True

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_reply_token(self, reply_token: str, user_id: str):
        now = int(time.time() * 1000)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO reply_tokens (reply_token, user_id, created_at)
                VALUES (?, ?, ?)
            """, (reply_token, user_id, now))
            conn.commit()

    def get_user_by_reply_token(self, reply_token: str) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM reply_tokens WHERE reply_token = ?", (reply_token,))
            row = cursor.fetchone()
            return row["user_id"] if row else None

    def save_message(self, message_id: str, user_id: str, direction: str, message_type: str, content: Any):
        now = int(time.time() * 1000)
        content_str = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO messages (message_id, user_id, direction, message_type, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (message_id, user_id, direction, message_type, content_str, now))
            conn.commit()

    def get_messages(self, user_id: str, limit: int = 50, before_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if before_id:
                cursor.execute("""
                    SELECT * FROM messages
                    WHERE user_id = ? AND id < ?
                    ORDER BY id DESC LIMIT ?
                """, (user_id, before_id, limit))
            else:
                cursor.execute("""
                    SELECT * FROM messages
                    WHERE user_id = ?
                    ORDER BY id DESC LIMIT ?
                """, (user_id, limit))
            rows = cursor.fetchall()
            messages = []
            for row in reversed(rows):
                d = dict(row)
                try:
                    d["content"] = json.loads(d["content"])
                except Exception:
                    pass
                messages.append(d)
            return messages

    def enqueue_offline_message(self, user_id: str, message_data: Any):
        now = int(time.time() * 1000)
        data_str = json.dumps(message_data, ensure_ascii=False) if not isinstance(message_data, str) else message_data
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO offline_queue (user_id, message_data, created_at)
                VALUES (?, ?, ?)
            """, (user_id, data_str, now))
            conn.commit()

    def pop_offline_messages(self, user_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, message_data FROM offline_queue
                WHERE user_id = ?
                ORDER BY id ASC
            """, (user_id,))
            rows = cursor.fetchall()
            if not rows:
                return []
            ids = [row["id"] for row in rows]
            messages = []
            for row in rows:
                try:
                    messages.append(json.loads(row["message_data"]))
                except Exception:
                    messages.append(row["message_data"])

            cursor.execute(f"DELETE FROM offline_queue WHERE id IN ({','.join(['?']*len(ids))})", ids)
            conn.commit()
            return messages
