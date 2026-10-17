"""
測試：加入 Bot（follow）/ 封鎖（unfollow）/ 刪除好友事件。
"""
import json
import unittest
from unittest import mock

from helpers import (BOT_HEADERS, CHANNEL_SECRET, app_headers, fresh_db, make_bot, make_invite, make_user,
                     platform_app)
from localbot.utils import check_signature


class TestFollow(unittest.TestCase):
    def setUp(self):
        fresh_db(f"follow_{self._testMethodName}")
        platform_app.app.config["TESTING"] = True
        self.client = platform_app.app.test_client()
        self.forwarded = []

        def fake_forward(bot, body, signature):
            self.assertTrue(check_signature(bot["channel_secret"], body, signature))
            payload = json.loads(body)
            self.assertEqual(payload["destination"], bot["bot_id"])
            self.forwarded.append((bot["bot_id"], payload["events"][0]))
            return 200

        for target, repl in (("forward_to_bot", fake_forward),
                             ("run_in_background", lambda f, *a: f(*a))):
            p = mock.patch.object(platform_app, target, side_effect=repl)
            p.start()
            self.addCleanup(p.stop)

    def _join(self, uid, code, headers=None):
        return self.client.post("/join", json={"userId": uid, "code": code, "displayName": uid}, headers=headers or {})

    def test_first_join_sends_follow_once(self):
        res = self._join("fu1", make_invite(max_uses=5))
        self.assertEqual(res.status_code, 200)
        token = res.get_json()["token"]
        self.assertEqual(len(self.forwarded), 1)
        bot_id, ev = self.forwarded[0]
        self.assertEqual(bot_id, "default")
        self.assertEqual(ev["type"], "follow")
        self.assertEqual(ev["source"]["userId"], "fu1")
        self.assertEqual(ev["follow"], {"isUnblocked": False})
        self.assertIn("webhookEventId", ev)
        # follow 的 replyToken 可以拿來回覆歡迎訊息
        with mock.patch.object(platform_app, "deliver_to_client", return_value=["id1"]):
            res = self.client.post("/v2/bot/message/reply", headers=BOT_HEADERS,
                                   json={"replyToken": ev["replyToken"], "messages": [{"type": "text", "text": "歡迎"}]})
        self.assertEqual(res.status_code, 200)
        # 再次用邀請碼加入同一個 Bot（已經是好友）不會重複送 follow
        self._join("fu1", make_invite(max_uses=5), {"X-LocalBot-Token": token})
        self.assertEqual(len(self.forwarded), 1)

    def test_join_second_bot_sends_follow_to_that_bot(self):
        make_bot("shop")
        res = self._join("fu1", make_invite())
        token = res.get_json()["token"]
        res = self._join("fu1", make_invite("shop"), {"X-LocalBot-Token": token})
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("token", res.get_json())  # 已有金鑰，不重發
        self.assertEqual([b for b, _ in self.forwarded], ["default", "shop"])

    def test_block_and_unblock(self):
        make_user("fu2")
        h = app_headers("fu2")
        res = self.client.post("/block", json={"userId": "fu2", "botId": "default", "blocked": True}, headers=h)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.forwarded[-1][1]["type"], "unfollow")
        self.assertNotIn("replyToken", self.forwarded[-1][1])
        self.assertTrue(platform_app.db.is_blocked("default", "fu2"))

        # 封鎖期間：App 不能傳訊息、Bot 推播不會送達、broadcast 會略過
        body = json.dumps({"destination": "default", "events": [
            {"type": "message", "replyToken": "r", "source": {"type": "user", "userId": "fu2"},
             "message": {"id": "m", "type": "text", "text": "hi"}}]})
        res = self.client.post("/callback", data=body, headers=h)
        self.assertEqual(res.status_code, 403)
        with mock.patch.object(platform_app.socketio, "emit") as emit:
            platform_app.deliver_to_client("default", "fu2", [{"type": "text", "text": "x"}])
            emit.assert_not_called()
        self.assertEqual(platform_app.db.get_messages("default", "fu2"), [])
        self.assertNotIn("fu2", platform_app.db.list_user_ids("default"))

        # 重複封鎖不會再送事件
        n = len(self.forwarded)
        self.client.post("/block", json={"userId": "fu2", "botId": "default", "blocked": True}, headers=h)
        self.assertEqual(len(self.forwarded), n)

        res = self.client.post("/block", json={"userId": "fu2", "botId": "default", "blocked": False}, headers=h)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.forwarded[-1][1]["type"], "follow")
        self.assertEqual(self.forwarded[-1][1]["follow"], {"isUnblocked": True})
        self.assertFalse(platform_app.db.is_blocked("default", "fu2"))

    def test_block_one_bot_does_not_affect_another(self):
        make_bot("shop")
        make_user("fu4", bots=("default", "shop"))
        h = app_headers("fu4")
        self.client.post("/block", json={"userId": "fu4", "botId": "shop", "blocked": True}, headers=h)
        self.assertTrue(platform_app.db.is_blocked("shop", "fu4"))
        self.assertFalse(platform_app.db.is_blocked("default", "fu4"))
        self.assertEqual([b for b, _ in self.forwarded], ["shop"])

    def test_block_requires_token_member_and_valid_body(self):
        make_user("fu3")
        base = {"userId": "fu3", "botId": "default", "blocked": True}
        self.assertEqual(self.client.post("/block", json=base).status_code, 401)
        self.assertEqual(self.client.post("/block", json={**base, "blocked": "yes"},
                                          headers=app_headers("fu3")).status_code, 400)
        self.assertEqual(self.client.post("/block", json={**base, "userId": "nobody"},
                                          headers=app_headers("nobody")).status_code, 401)
        make_bot("shop")
        self.assertEqual(self.client.post("/block", json={**base, "botId": "shop"},
                                          headers=app_headers("fu3")).status_code, 404)  # 不是它的好友

    def test_leave_removes_membership_and_sends_unfollow(self):
        make_bot("shop")
        make_user("fu5", bots=("default", "shop"))
        h = app_headers("fu5")
        platform_app.db.save_message("shop", "m1", "fu5", "incoming", "text", {"text": "x"})
        res = self.client.post("/leave", json={"userId": "fu5", "botId": "shop"}, headers=h)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.forwarded[-1][0], "shop")
        self.assertEqual(self.forwarded[-1][1]["type"], "unfollow")
        self.assertFalse(platform_app.db.is_member("shop", "fu5"))
        self.assertTrue(platform_app.db.is_member("default", "fu5"))
        self.assertEqual(platform_app.db.get_messages("shop", "fu5"), [])


if __name__ == "__main__":
    unittest.main()
