"""
測試：LINE 相容 /v2/bot/* 端點、Quick Reply 驗證、localbot.v3 相容層。
"""
import json
import unittest
from unittest import mock

from helpers import BOT_HEADERS, CHANNEL_ACCESS_TOKEN, fresh_db, make_bot, make_user, platform_app
from localbot.utils import calculate_signature

from localbot.v3 import WebhookHandler, WebhookParser
from localbot.v3.exceptions import InvalidSignatureError
from localbot.v3.messaging import (
    ApiClient, ApiException, BroadcastRequest, Configuration, FlexContainer, FlexMessage,
    MessageAction, MessagingApi, MessagingApiBlob, MulticastRequest, PostbackAction,
    PushMessageRequest, QuickReply, QuickReplyItem, ReplyMessageRequest,
    ShowLoadingAnimationRequest, TextMessage,
)
from localbot.v3.webhooks import (
    FollowEvent, MessageEvent, PostbackEvent, TextMessageContent, UserSource,
)

class _FakeResponse:
    """把 Flask test client 的回應包成 requests.Response 的樣子。"""

    def __init__(self, res):
        self.status_code = res.status_code
        self.reason = res.status
        self.content = res.get_data()
        self.text = res.get_data(as_text=True)
        self.headers = dict(res.headers)

    def json(self):
        return json.loads(self.text)


def _route_to_flask(client):
    def request(method, url, json=None, headers=None, timeout=None):
        path = url.split("://", 1)[-1]
        path = path[path.index("/"):]
        return _FakeResponse(client.open(path, method=method, json=json, headers=headers))
    return request


class BaseServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_db(f"test_v2_{cls.__name__}")
        platform_app.app.config["TESTING"] = True
        cls.client = platform_app.app.test_client()
        for uid in ("u_a", "u_b"):
            make_user(uid, name=uid.upper())
        _, cls.other_headers = make_bot("other")
        make_user("u_other", bots=("other",))  # 只加入另一個 Bot 的使用者
        platform_app.db.save_reply_token("default", "rt_1", "u_a")

    def setUp(self):
        self.delivered = []
        patcher = mock.patch.object(
            platform_app, "deliver_to_client",
            side_effect=lambda bot_id, uid, msgs: self.delivered.append((uid, msgs)) or [f"id{len(self.delivered)}"],
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class TestV2Endpoints(BaseServerTest):
    def test_requires_token(self):
        res = self.client.post("/v2/bot/message/push", json={"to": "u_a", "messages": [{"type": "text", "text": "x"}]})
        self.assertEqual(res.status_code, 401)

    def test_reply_returns_sent_messages(self):
        res = self.client.post("/v2/bot/message/reply", headers=BOT_HEADERS,
                               json={"replyToken": "rt_1", "messages": [{"type": "text", "text": "hi"}]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), {"sentMessages": [{"id": "id1"}]})
        self.assertEqual(self.delivered[0][0], "u_a")

    def test_reply_invalid_token(self):
        res = self.client.post("/v2/bot/message/reply", headers=BOT_HEADERS,
                               json={"replyToken": "nope", "messages": [{"type": "text", "text": "hi"}]})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["message"], "Invalid reply token")

    def test_too_many_messages(self):
        msgs = [{"type": "text", "text": str(i)} for i in range(6)]
        res = self.client.post("/v2/bot/message/push", headers=BOT_HEADERS, json={"to": "u_a", "messages": msgs})
        self.assertEqual(res.status_code, 400)

    def test_quick_reply_validation(self):
        item = {"type": "action", "action": {"type": "message", "label": "a", "text": "a"}}
        ok = {"type": "text", "text": "q", "quickReply": {"items": [item] * 13}}
        bad = {"type": "text", "text": "q", "quickReply": {"items": [item] * 14}}
        broken = {"type": "text", "text": "q", "quickReply": {"items": [{"type": "action"}]}}
        self.assertEqual(self.client.post("/v2/bot/message/push", headers=BOT_HEADERS,
                                          json={"to": "u_a", "messages": [ok]}).status_code, 200)
        self.assertEqual(self.client.post("/v2/bot/message/push", headers=BOT_HEADERS,
                                          json={"to": "u_a", "messages": [bad]}).status_code, 400)
        self.assertEqual(self.client.post("/v2/bot/message/push", headers=BOT_HEADERS,
                                          json={"to": "u_a", "messages": [broken]}).status_code, 400)
        # 舊版 /api/v1 端點也套用同樣驗證
        self.assertEqual(self.client.post("/api/v1/bot/push", headers=BOT_HEADERS,
                                          json={"to": "u_a", "messages": [bad]}).status_code, 400)

    def test_multicast_dedup_and_validation(self):
        res = self.client.post("/v2/bot/message/multicast", headers=BOT_HEADERS,
                               json={"to": ["u_a", "u_b", "u_a"], "messages": [{"type": "text", "text": "m"}]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual([d[0] for d in self.delivered], ["u_a", "u_b"])
        res = self.client.post("/v2/bot/message/multicast", headers=BOT_HEADERS,
                               json={"to": ["../etc"], "messages": [{"type": "text", "text": "m"}]})
        self.assertEqual(res.status_code, 400)

    def test_broadcast_and_narrowcast(self):
        res = self.client.post("/v2/bot/message/broadcast", headers=BOT_HEADERS,
                               json={"messages": [{"type": "text", "text": "b"}]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sorted(d[0] for d in self.delivered), ["u_a", "u_b"])
        res = self.client.post("/v2/bot/message/narrowcast", headers=BOT_HEADERS,
                               json={"messages": [{"type": "text", "text": "n"}]})
        self.assertEqual(res.status_code, 202)
        self.assertIn("X-Line-Request-Id", res.headers)

    def test_quota_and_profile(self):
        self.assertEqual(self.client.get("/v2/bot/message/quota", headers=BOT_HEADERS).get_json(), {"type": "none"})
        self.assertEqual(self.client.get("/v2/bot/message/quota/consumption", headers=BOT_HEADERS).get_json(),
                         {"totalUsage": 0})
        res = self.client.get("/v2/bot/profile/u_a", headers=BOT_HEADERS)
        self.assertEqual(res.get_json()["displayName"], "U_A")
        self.assertEqual(self.client.get("/v2/bot/profile/nobody", headers=BOT_HEADERS).status_code, 404)

    def test_bots_are_isolated(self):
        msg = [{"type": "text", "text": "x"}]
        # 推播給不是自己好友的使用者 → 400；reply token 也不能跨 Bot 使用
        res = self.client.post("/v2/bot/message/push", headers=BOT_HEADERS, json={"to": "u_other", "messages": msg})
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/v2/bot/message/reply", headers=self.other_headers,
                               json={"replyToken": "rt_1", "messages": msg})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.client.get("/v2/bot/profile/u_other", headers=BOT_HEADERS).status_code, 404)
        self.assertEqual(self.client.get("/v2/bot/profile/u_other", headers=self.other_headers).status_code, 200)
        # multicast 略過非好友；broadcast 只送給自己的好友
        self.client.post("/v2/bot/message/multicast", headers=BOT_HEADERS,
                         json={"to": ["u_a", "u_other"], "messages": msg})
        self.assertEqual([d[0] for d in self.delivered], ["u_a"])
        self.delivered.clear()
        self.client.post("/v2/bot/message/broadcast", headers=self.other_headers, json={"messages": msg})
        self.assertEqual([d[0] for d in self.delivered], ["u_other"])

    def test_disabled_bot_token_is_rejected(self):
        make_bot("off", enabled=False)
        res = self.client.get("/v2/bot/message/quota", headers={"Authorization": "Bearer token-off"})
        self.assertEqual(res.status_code, 401)

    def test_loading_animation(self):
        with mock.patch.object(platform_app.socketio, "emit") as emit:
            platform_app.connected_users["u_a"] = {"sid1"}
            try:
                res = self.client.post("/v2/bot/chat/loading/start", headers=BOT_HEADERS,
                                       json={"chatId": "u_a", "loadingSeconds": 10})
            finally:
                platform_app.connected_users.pop("u_a", None)
            self.assertEqual(res.status_code, 202)
            emit.assert_called_once_with("loading", {"botId": "default", "chatId": "u_a", "loadingSeconds": 10}, room="u_a")
        res = self.client.post("/v2/bot/chat/loading/start", headers=BOT_HEADERS,
                               json={"chatId": "u_a", "loadingSeconds": 7})
        self.assertEqual(res.status_code, 400)


class TestV3MessagingApi(BaseServerTest):
    def setUp(self):
        super().setUp()
        self.api_client = ApiClient(Configuration(access_token=CHANNEL_ACCESS_TOKEN, host="http://localbot.test"))
        self.api_client._session.request = _route_to_flask(self.client)
        self.api = MessagingApi(self.api_client)

    def test_reply_with_quick_reply(self):
        msg = TextMessage(text="要繼續嗎？", quick_reply=QuickReply(items=[
            QuickReplyItem(action=MessageAction(label="是", text="是")),
            QuickReplyItem(action=PostbackAction(label="否", data="ans=no", display_text="否")),
        ]))
        resp = self.api.reply_message(ReplyMessageRequest(reply_token="rt_1", messages=[msg]))
        self.assertEqual(resp.sent_messages[0].id, "id1")
        sent = self.delivered[0][1][0]
        self.assertEqual(sent["quickReply"]["items"][0],
                         {"type": "action", "action": {"type": "message", "label": "是", "text": "是"}})
        self.assertEqual(sent["quickReply"]["items"][1]["action"]["displayText"], "否")

    def test_reply_with_http_info(self):
        info = self.api.reply_message_with_http_info(
            ReplyMessageRequest(reply_token="rt_1", messages=[TextMessage(text="x")]))
        self.assertEqual(info.status_code, 200)

    def test_push_multicast_broadcast(self):
        self.api.push_message(PushMessageRequest(to="u_b", messages=[TextMessage(text="p")]))
        self.api.multicast(MulticastRequest(to=["u_a", "u_b"], messages=[TextMessage(text="m")]))
        self.api.broadcast(BroadcastRequest(messages=[TextMessage(text="b")]))
        self.assertEqual(len(self.delivered), 5)

    def test_flex_from_json(self):
        bubble = FlexContainer.from_json(json.dumps({"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": []}}))
        self.api.push_message(PushMessageRequest(to="u_a", messages=[FlexMessage(alt_text="f", contents=bubble)]))
        self.assertEqual(self.delivered[0][1][0]["contents"]["type"], "bubble")

    def test_profile_and_errors(self):
        profile = self.api.get_profile("u_a")
        self.assertEqual(profile.display_name, "U_A")
        self.assertEqual(profile.user_id, "u_a")
        with self.assertRaises(ApiException) as ctx:
            self.api.reply_message(ReplyMessageRequest(reply_token="bad", messages=[TextMessage(text="x")]))
        self.assertEqual(ctx.exception.status, 400)

    def test_loading_and_quota(self):
        self.api.show_loading_animation(ShowLoadingAnimationRequest(chat_id="u_a", loading_seconds=5))
        self.assertEqual(self.api.get_message_quota().type, "none")
        self.assertEqual(self.api.get_message_quota_consumption().total_usage, 0)

    def test_blob_content_not_found(self):
        blob = MessagingApiBlob(self.api_client)
        with self.assertRaises(ApiException) as ctx:
            blob.get_message_content("missing_id")
        self.assertEqual(ctx.exception.status, 404)


class TestV3WebhookHandler(unittest.TestCase):
    SECRET = "v3_secret"

    def _body(self, *events):
        return json.dumps({"destination": "localbot", "events": list(events)})

    def test_dispatch_and_signature(self):
        handler = WebhookHandler(self.SECRET)
        got = {}

        @handler.add(MessageEvent, message=TextMessageContent)
        def on_text(event):
            got["text"] = (event.reply_token, event.source.user_id, event.message.text)

        @handler.add(PostbackEvent)
        def on_postback(event, destination):
            got["postback"] = (event.postback.data, event.postback.params, destination)

        @handler.add(FollowEvent)
        def on_follow(event):
            got["follow"] = isinstance(event.source, UserSource)

        body = self._body(
            {"type": "message", "replyToken": "r1", "source": {"type": "user", "userId": "u1"},
             "message": {"type": "text", "id": "m1", "text": "哈囉"}},
            {"type": "postback", "replyToken": "r2", "source": {"type": "user", "userId": "u1"},
             "postback": {"data": "a=1", "params": {"date": "2026-10-13"}}},
            {"type": "follow", "replyToken": "r3", "source": {"type": "user", "userId": "u1"}},
        )
        handler.handle(body, calculate_signature(self.SECRET, body))
        self.assertEqual(got["text"], ("r1", "u1", "哈囉"))
        self.assertEqual(got["postback"], ("a=1", {"date": "2026-10-13"}, "localbot"))
        self.assertTrue(got["follow"])

        with self.assertRaises(InvalidSignatureError):
            handler.handle(body, "bad")
        with self.assertRaises(InvalidSignatureError):
            handler.handle(body, None)

    def test_default_handler(self):
        handler = WebhookHandler(self.SECRET)
        seen = []
        handler.default()(lambda event: seen.append(type(event).__name__))
        body = self._body({"type": "message", "replyToken": "r", "source": {"type": "user", "userId": "u"},
                           "message": {"type": "image", "id": "i1"}})
        handler.handle(body, calculate_signature(self.SECRET, body))
        self.assertEqual(seen, ["MessageEvent"])

    def test_parser(self):
        parser = WebhookParser(self.SECRET)
        body = self._body({"type": "unfollow", "source": {"type": "user", "userId": "u"}})
        events = parser.parse(body, calculate_signature(self.SECRET, body))
        self.assertEqual(type(events[0]).__name__, "UnfollowEvent")
        payload = parser.parse(body, calculate_signature(self.SECRET, body), as_payload=True)
        self.assertEqual(payload.destination, "localbot")
        with self.assertRaises(InvalidSignatureError):
            parser.parse(body, "bad")


if __name__ == "__main__":
    unittest.main()


class TestV1NewMethods(BaseServerTest):
    def test_v1_multicast_broadcast_quota_loading(self):
        from localbot import LineBotApi
        from localbot.models import QuickReply, QuickReplyButton, MessageAction as V1MessageAction, TextSendMessage

        api = LineBotApi(CHANNEL_ACCESS_TOKEN, server_url="http://localbot.test")
        with mock.patch("requests.request", side_effect=_route_to_flask(self.client)):
            qr = QuickReply(items=[QuickReplyButton(action=V1MessageAction(label="好", text="好"))])
            api.multicast(["u_a", "u_b"], TextSendMessage(text="hi", quick_reply=qr))
            api.broadcast(TextSendMessage(text="all"))
            self.assertEqual(api.get_message_quota().type, "none")
            self.assertEqual(api.get_message_quota_consumption().total_usage, 0)
            api.show_loading_animation("u_a", 5)
        self.assertEqual(len(self.delivered), 4)
        self.assertEqual(self.delivered[0][1][0]["quickReply"]["items"][0]["action"]["text"], "好")
