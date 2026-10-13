"""
End-to-end integration tests for the Platform (app.py).
Tests the forwarding flow and the security checks:
Flutter → Platform → Bot → Platform API → Socket.IO delivery.
"""
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

# 測試時使用暫存資料夾，不要寫入正式的 media / db / 金鑰檔
_TMP = tempfile.mkdtemp()
os.environ.setdefault("LOCALBOT_SECRETS_FILE", os.path.join(_TMP, "secrets.json"))
os.environ.setdefault("LOCALBOT_MEDIA_DIR", os.path.join(_TMP, "media"))
os.environ.setdefault("LOCALBOT_DB_PATH", os.path.join(_TMP, "test.db"))

import app as platform_app  # noqa: E402
from database import Database  # noqa: E402
from localbot.utils import calculate_signature  # noqa: E402
from localconfig import APP_SECRET, CHANNEL_ACCESS_TOKEN  # noqa: E402

USER_ID = "device_user_001"
APP_TOKEN = calculate_signature(APP_SECRET, USER_ID)
BOT_HEADERS = {"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"}
APP_HEADERS = {"X-LocalBot-Token": APP_TOKEN}


class TestPlatformE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform_app.db = Database(os.path.join(_TMP, "test_e2e.db"))
        platform_app.app.config['TESTING'] = True
        cls.client = platform_app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)

    def test_01_health(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertNotIn("botWebhookUrl", data)

    def test_02_register_device(self):
        payload = {"userId": USER_ID, "displayName": "Flutter Tester"}
        res = self.client.post("/register", json=payload, headers=APP_HEADERS)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["userId"], USER_ID)
        self.assertNotIn("deviceSecret", data)
        self.assertIsNotNone(platform_app.db.get_user(USER_ID))

    def test_02b_register_requires_token(self):
        res = self.client.post("/register", json={"userId": "x1"})
        self.assertEqual(res.status_code, 401)

    def test_03_bot_reply_api(self):
        reply_token = "manual_reply_tok"
        platform_app.db.save_reply_token(reply_token, USER_ID)
        res = self.client.post("/api/v1/bot/reply", headers=BOT_HEADERS, json={
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": "Hello from Bot via reply API!"}]
        })
        self.assertEqual(res.status_code, 200)
        offline = platform_app.db.pop_offline_messages(USER_ID)
        self.assertGreaterEqual(len(offline), 1)
        self.assertEqual(offline[0]["content"]["text"], "Hello from Bot via reply API!")

    def test_04_bot_push_api(self):
        res = self.client.post("/api/v1/bot/push", headers=BOT_HEADERS, json={
            "to": USER_ID,
            "messages": [{"type": "text", "text": "Push notification from Bot!"}]
        })
        self.assertEqual(res.status_code, 200)
        offline = platform_app.db.pop_offline_messages(USER_ID)
        self.assertGreaterEqual(len(offline), 1)
        self.assertEqual(offline[0]["content"]["text"], "Push notification from Bot!")

    def test_04b_bot_api_requires_token(self):
        for path in ("/api/v1/bot/push", "/api/v1/bot/reply"):
            res = self.client.post(path, json={"to": USER_ID, "messages": []})
            self.assertEqual(res.status_code, 401)
            res = self.client.post(path, json={"to": USER_ID, "messages": []},
                                   headers={"Authorization": "Bearer wrong"})
            self.assertEqual(res.status_code, 401)
        self.assertEqual(self.client.get(f"/api/v1/bot/profile/{USER_ID}").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/bot/content/abc").status_code, 401)

    def test_05_sticker_and_media(self):
        res = self.client.get("/stickers/list")
        self.assertEqual(res.status_code, 200)
        res_sticker = self.client.get("/stickers/1/1")
        self.assertEqual(res_sticker.status_code, 200)
        # XSS payload in sticker id must be rejected
        res_bad = self.client.get("/stickers/1/<script>")
        self.assertEqual(res_bad.status_code, 400)

    def test_06_upload_media(self):
        res = self.client.post(
            "/upload", headers=APP_HEADERS,
            data={"userId": USER_ID, "messageId": "platform_img_001",
                  "file": (io.BytesIO(b"fake image data"), "photo.jpg")},
            content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["filename"], "platform_img_001.jpg")

    def test_06b_upload_rejects_bad_input(self):
        # 沒有 token
        res = self.client.post(
            "/upload",
            data={"userId": USER_ID, "messageId": "a1", "file": (io.BytesIO(b"x"), "a.jpg")},
            content_type="multipart/form-data")
        self.assertEqual(res.status_code, 401)
        # 路徑穿越
        res = self.client.post(
            "/upload", headers=APP_HEADERS,
            data={"userId": USER_ID, "messageId": "../../evil",
                  "file": (io.BytesIO(b"x"), "a.jpg")},
            content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400)
        # 不允許的副檔名
        res = self.client.post(
            "/upload", headers=APP_HEADERS,
            data={"userId": USER_ID, "messageId": "a2",
                  "file": (io.BytesIO(b"<script>"), "a.html")},
            content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400)

    def test_07_bot_content_api(self):
        self.client.post(
            "/upload", headers=APP_HEADERS,
            data={"userId": USER_ID, "messageId": "content_test_001",
                  "file": (io.BytesIO(b"binary content for retrieval test"), "audio.m4a")},
            content_type="multipart/form-data")
        res = self.client.get("/api/v1/bot/content/content_test_001", headers=BOT_HEADERS)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, b"binary content for retrieval test")

    def test_08_bot_profile_api(self):
        res = self.client.get(f"/api/v1/bot/profile/{USER_ID}", headers=BOT_HEADERS)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["userId"], USER_ID)
        self.assertEqual(data["displayName"], "Flutter Tester")

    def test_09_callback_signature(self):
        body = json.dumps({"destination": "localbot", "events": [{
            "type": "message", "replyToken": "r1",
            "source": {"type": "user", "userId": USER_ID},
            "message": {"id": "m1", "type": "text", "text": "hi"}}]})
        # 無簽名 → 401
        res = self.client.post("/callback", data=body, content_type="application/json")
        self.assertEqual(res.status_code, 401)
        # 正確簽名 → 轉發給 Bot
        sig = calculate_signature(APP_SECRET, body)
        with mock.patch.object(platform_app, "forward_to_bot", return_value=200) as fwd:
            res = self.client.post("/callback", data=body, content_type="application/json",
                                   headers={"X-LocalBot-Signature": sig})
        self.assertEqual(res.status_code, 200)
        fwd.assert_called_once()

    def test_10_history_requires_token(self):
        self.assertEqual(self.client.get(f"/history?userId={USER_ID}").status_code, 401)
        res = self.client.get(f"/history?userId={USER_ID}&limit=99999", headers=APP_HEADERS)
        self.assertEqual(res.status_code, 200)

    def test_11_socket_requires_token(self):
        sc = platform_app.socketio.test_client(platform_app.app, auth={"userId": USER_ID})
        self.assertFalse(sc.is_connected())
        sc = platform_app.socketio.test_client(
            platform_app.app, auth={"userId": USER_ID, "token": APP_TOKEN})
        self.assertTrue(sc.is_connected())
        sc.disconnect()


if __name__ == "__main__":
    unittest.main()
