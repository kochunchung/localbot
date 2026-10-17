"""
End-to-end integration tests for the Platform (app.py).
Tests the forwarding flow and the security checks:
Flutter → Platform → Bot → Platform API → Socket.IO delivery.
"""
import io
import json
import unittest
from unittest import mock

from helpers import BOT_HEADERS, fresh_db, make_bot, make_invite, platform_app

USER_ID = "device_user_001"


class TestPlatformE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_db("test_e2e")
        platform_app.app.config['TESTING'] = True
        cls.client = platform_app.app.test_client()

    @classmethod
    def join(cls):
        res = cls.client.post("/join", json={"userId": USER_ID, "displayName": "Flutter Tester",
                                             "code": make_invite(max_uses=5)})
        cls.token = res.get_json()["token"]
        cls.headers = {"X-LocalBot-Token": cls.token}
        return res

    def test_01_health(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertNotIn("botWebhookUrl", data)

    def test_02_join_with_invite(self):
        res = self.join()
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["userId"], USER_ID)
        self.assertEqual(data["bot"]["botId"], "default")
        self.assertTrue(data["token"].startswith("lbu_"))
        self.assertNotIn("channelSecret", json.dumps(data))
        self.assertIsNotNone(platform_app.db.get_user(USER_ID))
        # 伺服器只存雜湊
        self.assertNotIn(data["token"], json.dumps(platform_app.db.get_user(USER_ID)))

    def test_02b_join_requires_valid_invite(self):
        res = self.client.post("/join", json={"userId": "x1", "code": "WRONGCODE1"})
        self.assertEqual(res.status_code, 404)
        self.assertIsNone(platform_app.db.get_user("x1"))

    def test_03_bot_reply_api(self):
        reply_token = "manual_reply_tok"
        platform_app.db.save_reply_token("default", reply_token, USER_ID)
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
            "/upload", headers=self.headers,
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
            "/upload", headers=self.headers,
            data={"userId": USER_ID, "messageId": "../../evil",
                  "file": (io.BytesIO(b"x"), "a.jpg")},
            content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400)
        # 不允許的副檔名
        res = self.client.post(
            "/upload", headers=self.headers,
            data={"userId": USER_ID, "messageId": "a2",
                  "file": (io.BytesIO(b"<script>"), "a.html")},
            content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400)

    def test_07_bot_content_api(self):
        self.client.post(
            "/upload", headers=self.headers,
            data={"userId": USER_ID, "messageId": "content_test_001",
                  "file": (io.BytesIO(b"binary content for retrieval test"), "audio.m4a")},
            content_type="multipart/form-data")
        # 只有這個 Bot 收過的訊息，它才能下載內容
        res = self.client.get("/api/v1/bot/content/content_test_001", headers=BOT_HEADERS)
        self.assertEqual(res.status_code, 404)
        platform_app.db.save_message("default", "content_test_001", USER_ID, "incoming", "audio", {"id": "content_test_001"})
        res = self.client.get("/api/v1/bot/content/content_test_001", headers=BOT_HEADERS)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, b"binary content for retrieval test")
        _, other = make_bot("other_bot")
        self.assertEqual(self.client.get("/api/v1/bot/content/content_test_001", headers=other).status_code, 404)

    def test_08_bot_profile_api(self):
        res = self.client.get(f"/api/v1/bot/profile/{USER_ID}", headers=BOT_HEADERS)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["userId"], USER_ID)
        self.assertEqual(data["displayName"], "Flutter Tester")

    def test_09_callback_signature(self):
        body = json.dumps({"destination": "default", "events": [{
            "type": "message", "replyToken": "r1",
            "source": {"type": "user", "userId": USER_ID},
            "message": {"id": "m1", "type": "text", "text": "hi"}}]})
        # 沒有金鑰 → 401；錯誤的金鑰 → 401
        res = self.client.post("/callback", data=body, content_type="application/json")
        self.assertEqual(res.status_code, 401)
        res = self.client.post("/callback", data=body, content_type="application/json",
                               headers={"X-LocalBot-Token": "lbu_wrong"})
        self.assertEqual(res.status_code, 401)
        # 正確金鑰 → 轉發給 Bot
        with mock.patch.object(platform_app, "forward_to_bot", return_value=200) as fwd:
            res = self.client.post("/callback", data=body, content_type="application/json", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        fwd.assert_called_once()

    def test_10_history_requires_token(self):
        self.assertEqual(self.client.get(f"/history?userId={USER_ID}&botId=default").status_code, 401)
        res = self.client.get(f"/history?userId={USER_ID}&botId=default&limit=99999", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.get(f"/history?userId={USER_ID}", headers=self.headers).status_code, 400)

    def test_11_socket_requires_token(self):
        sc = platform_app.socketio.test_client(platform_app.app, auth={"userId": USER_ID})
        self.assertFalse(sc.is_connected())
        sc = platform_app.socketio.test_client(platform_app.app, auth={"userId": USER_ID, "token": "lbu_wrong"})
        self.assertFalse(sc.is_connected())
        sc = platform_app.socketio.test_client(
            platform_app.app, auth={"userId": USER_ID, "token": self.token})
        self.assertTrue(sc.is_connected())
        sc.disconnect()

    def test_12_me_lists_bots(self):
        res = self.client.get(f"/me?userId={USER_ID}", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        bots = res.get_json()["bots"]
        self.assertEqual([b["botId"] for b in bots], ["default"])
        self.assertNotIn("webhook", json.dumps(bots).lower())
        self.assertEqual(self.client.get(f"/me?userId={USER_ID}").status_code, 401)


if __name__ == "__main__":
    unittest.main()
