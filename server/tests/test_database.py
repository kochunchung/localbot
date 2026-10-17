"""
Unit tests for Database（多 Bot）.
"""
import os
import shutil
import sqlite3
import tempfile
import unittest

from database import Database


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = Database(self.db_path)
        self.db.create_bot("b1", "Bot 1", None, "s1", "t1", "http://x/1")
        self.db.create_bot("b2", "Bot 2", None, "s2", "t2", "http://x/2")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_user_and_token(self):
        self.assertTrue(self.db.create_user("u1", "Alice", "hash1"))
        self.assertFalse(self.db.create_user("u1", "Other", "hash2"))
        user = self.db.get_user("u1")
        self.assertEqual(user["display_name"], "Alice")
        self.assertEqual(self.db.get_token_hash("u1"), "hash1")
        self.assertTrue(self.db.revoke_user_token("u1"))
        self.assertIsNone(self.db.get_token_hash("u1"))
        self.assertIsNotNone(self.db.get_user("u1")["revoked_at"])
        self.assertTrue(self.db.set_user_token("u1", "hash3"))
        self.assertEqual(self.db.get_token_hash("u1"), "hash3")
        self.assertIsNone(self.db.get_user("u1")["revoked_at"])

    def test_membership_is_per_bot(self):
        self.db.create_user("u1", "A", "h")
        self.assertTrue(self.db.add_membership("b1", "u1"))
        self.assertFalse(self.db.add_membership("b1", "u1"))
        self.assertTrue(self.db.is_member("b1", "u1"))
        self.assertFalse(self.db.is_member("b2", "u1"))
        self.db.add_membership("b2", "u1")
        self.db.set_blocked("b1", "u1", True)
        self.assertTrue(self.db.is_blocked("b1", "u1"))
        self.assertFalse(self.db.is_blocked("b2", "u1"))
        self.assertEqual(self.db.list_user_ids("b1"), [])
        self.assertEqual(self.db.list_user_ids("b1", include_blocked=True), ["u1"])
        self.assertEqual(self.db.list_user_ids("b2"), ["u1"])
        self.assertTrue(self.db.remove_membership("b2", "u1"))
        self.assertFalse(self.db.is_member("b2", "u1"))

    def test_reply_token_mapping_is_per_bot(self):
        self.db.save_reply_token("b1", "token_xyz", "user_123")
        self.assertEqual(self.db.get_user_by_reply_token("b1", "token_xyz"), "user_123")
        self.assertIsNone(self.db.get_user_by_reply_token("b2", "token_xyz"))
        self.assertIsNone(self.db.get_user_by_reply_token("b1", "nonexistent"))

    def test_offline_queue(self):
        self.db.enqueue_offline_message("b1", "u_offline", {"text": "msg 1"})
        self.db.enqueue_offline_message("b2", "u_offline", {"text": "msg 2"})
        msgs = self.db.pop_offline_messages("u_offline")
        self.assertEqual([m["text"] for m in msgs], ["msg 1", "msg 2"])
        self.assertEqual(self.db.pop_offline_messages("u_offline"), [])

    def test_message_history_is_per_bot(self):
        self.db.save_message("b1", "m1", "u_hist", "incoming", "text", {"text": "hi"})
        self.db.save_message("b1", "m2", "u_hist", "outgoing", "text", {"text": "hello"})
        self.db.save_message("b2", "m3", "u_hist", "outgoing", "text", {"text": "other"})
        hist = self.db.get_messages("b1", "u_hist")
        self.assertEqual([m["message_id"] for m in hist], ["m1", "m2"])
        self.assertEqual(len(self.db.get_messages("b2", "u_hist")), 1)
        self.assertTrue(self.db.has_message("b1", "m1"))
        self.assertFalse(self.db.has_message("b2", "m1"))

    def test_invites(self):
        self.db.create_invite("CODE1", "b1", "label", 2, None)
        self.assertTrue(self.db.consume_invite("CODE1"))
        self.assertTrue(self.db.consume_invite("CODE1"))
        self.assertFalse(self.db.consume_invite("CODE1"))  # 用完
        self.db.refund_invite("CODE1")
        self.assertTrue(self.db.consume_invite("CODE1"))
        self.db.create_invite("CODE2", "b1", None, 5, 1000)
        self.assertFalse(self.db.consume_invite("CODE2", now_ms=2000))  # 過期
        self.assertTrue(self.db.consume_invite("CODE2", now_ms=500))
        self.db.revoke_invite("CODE2")
        self.assertFalse(self.db.consume_invite("CODE2", now_ms=500))

    def test_delete_bot_removes_its_data_only(self):
        self.db.create_user("u1", "A", "h")
        for b in ("b1", "b2"):
            self.db.add_membership(b, "u1")
            self.db.save_message(b, f"m-{b}", "u1", "outgoing", "text", {"text": "x"})
            self.db.create_richmenu(b, f"rm-{b}", {"name": "m"})
        self.db.create_invite("CODE", "b1", None, 1, None)
        menus = self.db.delete_bot("b1")
        self.assertEqual([m["richMenuId"] for m in menus], ["rm-b1"])
        self.assertIsNone(self.db.get_bot("b1"))
        self.assertEqual(self.db.get_messages("b1", "u1"), [])
        self.assertIsNone(self.db.get_invite("CODE"))
        self.assertTrue(self.db.is_member("b2", "u1"))
        self.assertEqual(len(self.db.get_messages("b2", "u1")), 1)

    def test_legacy_database_is_migrated_to_default_bot(self):
        path = os.path.join(self.temp_dir, "old.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE users (user_id TEXT PRIMARY KEY, device_secret TEXT NOT NULL, "
                     "display_name TEXT, created_at INTEGER NOT NULL, blocked INTEGER NOT NULL DEFAULT 0)")
        conn.execute("INSERT INTO users VALUES ('old', '-', 'Old', 0, 1)")
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO settings VALUES ('default_richmenu', 'rm1')")
        conn.commit()
        conn.close()
        db = Database(path)
        self.assertTrue(db.is_member("default", "old"))
        self.assertTrue(db.is_blocked("default", "old"))
        self.assertIsNone(db.get_token_hash("old"))  # 舊使用者沒有金鑰，要用邀請碼重新加入
        self.assertEqual(db.get_setting("default_richmenu:default"), "rm1")
        Database(path)  # 再開一次不會重複搬移
        self.assertEqual(len(db.list_user_ids("default", include_blocked=True)), 1)


if __name__ == "__main__":
    unittest.main()
