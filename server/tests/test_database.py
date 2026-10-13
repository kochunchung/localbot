"""
Unit tests for Database and Bridge logic.
"""
import os
import unittest
import tempfile
import shutil
from database import Database


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = Database(self.db_path)

    def tearDown(self):
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def test_user_registration(self):
        self.db.register_user("u1", "secret1", "Alice")
        user = self.db.get_user("u1")
        self.assertIsNotNone(user)
        self.assertEqual(user["user_id"], "u1")
        self.assertEqual(user["device_secret"], "secret1")
        self.assertEqual(user["display_name"], "Alice")

    def test_reply_token_mapping(self):
        self.db.save_reply_token("token_xyz", "user_123")
        uid = self.db.get_user_by_reply_token("token_xyz")
        self.assertEqual(uid, "user_123")
        self.assertIsNone(self.db.get_user_by_reply_token("nonexistent"))

    def test_offline_queue(self):
        self.db.enqueue_offline_message("u_offline", {"text": "msg 1"})
        self.db.enqueue_offline_message("u_offline", {"text": "msg 2"})

        msgs = self.db.pop_offline_messages("u_offline")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["text"], "msg 1")
        self.assertEqual(msgs[1]["text"], "msg 2")

        # Second pop should be empty
        msgs2 = self.db.pop_offline_messages("u_offline")
        self.assertEqual(len(msgs2), 0)

    def test_message_history(self):
        self.db.save_message("m1", "u_hist", "incoming", "text", {"text": "hi"})
        self.db.save_message("m2", "u_hist", "outgoing", "text", {"text": "hello"})

        hist = self.db.get_messages("u_hist")
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["message_id"], "m1")
        self.assertEqual(hist[1]["message_id"], "m2")


if __name__ == "__main__":
    unittest.main()
