"""
測試：多 Bot／多使用者金鑰 — 邀請碼加入、每位使用者自己的金鑰、Bot 與邀請碼管理 API。
"""
import json
import time
import unittest
from urllib.parse import parse_qs, urlparse
from unittest import mock

import admin_panel
import localconfig as cfg
from helpers import (BOT_HEADERS, app_headers, fresh_db, make_bot, make_invite, make_user, platform_app)


class Base(unittest.TestCase):
    def setUp(self):
        fresh_db(f"mb_{self._testMethodName}")
        platform_app.app.config["TESTING"] = True
        admin_panel.reset_login_limiter()
        self.client = platform_app.app.test_client()
        self.events = []
        for target, repl in (("send_platform_event",
                              lambda bot_id, uid, typ, **kw: self.events.append((bot_id, uid, typ))),):
            p = mock.patch.object(platform_app, target, side_effect=repl)
            p.start()
            self.addCleanup(p.stop)

    def join(self, uid, code, headers=None, name=None):
        body = {"userId": uid, "code": code}
        if name:
            body["displayName"] = name
        return self.client.post("/join", json=body, headers=headers or {})


class TestJoin(Base):
    def test_new_user_gets_own_key_and_membership(self):
        code = make_invite()
        res = self.join("alice", code, name="Alice")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["token"].startswith("lbu_"))
        self.assertEqual(data["bot"], {"botId": "default", "name": "預設 Bot", "description": "第一次啟動時自動建立", "avatarUrl": ""})
        self.assertTrue(platform_app.db.is_member("default", "alice"))
        self.assertEqual(platform_app.db.get_user("alice")["display_name"], "Alice")
        self.assertEqual(self.events, [("default", "alice", "follow")])
        # 伺服器只存雜湊
        self.assertEqual(platform_app.db.get_token_hash("alice"), platform_app.hash_token(data["token"]))
        self.assertNotEqual(platform_app.db.get_token_hash("alice"), data["token"])
        # 兩個使用者的金鑰不同
        other = self.join("bob", make_invite(), name="Bob").get_json()["token"]
        self.assertNotEqual(other, data["token"])

    def test_code_format_is_forgiving(self):
        code = make_invite()
        pretty = f"{code[:5].lower()} - {code[5:]}"
        self.assertEqual(self.join("alice", pretty).status_code, 200)

    def test_single_use_invite(self):
        code = make_invite(max_uses=1)
        self.assertEqual(self.join("a1", code).status_code, 200)
        self.assertEqual(self.join("a2", code).status_code, 404)
        self.assertFalse(platform_app.db.is_member("default", "a2"))
        self.assertIsNone(platform_app.db.get_user("a2"))

    def test_multi_use_invite_and_counter(self):
        code = make_invite(max_uses=3)
        for i in range(3):
            self.assertEqual(self.join(f"m{i}", code).status_code, 200)
        self.assertEqual(self.join("m9", code).status_code, 404)
        self.assertEqual(platform_app.db.get_invite(code)["uses"], 3)

    def test_expired_and_revoked_invites(self):
        expired = make_invite(expires_at=int(time.time() * 1000) - 1000)
        self.assertEqual(self.join("e1", expired).status_code, 404)
        revoked = make_invite()
        platform_app.db.revoke_invite(revoked)
        self.assertEqual(self.join("e2", revoked).status_code, 404)
        self.assertEqual(self.join("e3", "NOSUCHCODE").status_code, 404)
        self.assertEqual(self.join("e4", "").status_code, 404)
        self.assertEqual(self.join("e5", None).status_code, 404)

    def test_invite_for_disabled_bot_is_refused(self):
        make_bot("shop")
        code = make_invite("shop")
        platform_app.db.update_bot("shop", enabled=False)
        self.assertEqual(self.join("d1", code).status_code, 404)
        self.assertEqual(platform_app.db.get_invite(code)["uses"], 0)

    def test_invalid_user_id(self):
        for uid in ("../x", "", None, "a b"):
            res = self.client.post("/join", json={"userId": uid, "code": make_invite()})
            self.assertEqual(res.status_code, 400, uid)

    def test_join_second_bot_requires_existing_key(self):
        make_bot("shop")
        token = self.join("alice", make_invite()).get_json()["token"]
        code = make_invite("shop")
        # 沒帶金鑰 / 帶錯金鑰：不能冒用已存在的 userId 加入
        self.assertEqual(self.join("alice", code).status_code, 401)
        self.assertEqual(self.join("alice", code, {"X-LocalBot-Token": "lbu_wrong"}).status_code, 401)
        self.assertFalse(platform_app.db.is_member("shop", "alice"))
        self.assertEqual(platform_app.db.get_invite(code)["uses"], 0)  # 失敗不消耗邀請碼
        res = self.join("alice", code, {"X-LocalBot-Token": token})
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("token", res.get_json())
        self.assertTrue(platform_app.db.is_member("shop", "alice"))

    def test_rejoin_existing_bot_does_not_consume_invite(self):
        token = self.join("alice", make_invite()).get_json()["token"]
        code = make_invite(max_uses=1)
        self.assertEqual(self.join("alice", code, {"X-LocalBot-Token": token}).status_code, 200)
        self.assertEqual(platform_app.db.get_invite(code)["uses"], 0)
        self.assertEqual(len([e for e in self.events if e[2] == "follow"]), 1)

    def test_revoked_user_can_rejoin_with_new_key(self):
        make_user("old")
        platform_app.db.revoke_user_token("old")
        res = self.join("old", make_invite())
        self.assertEqual(res.status_code, 200)
        self.assertIn("token", res.get_json())
        self.assertEqual(self.client.get("/me?userId=old", headers={"X-LocalBot-Token": res.get_json()["token"]}).status_code, 200)

    def test_legacy_user_without_key_can_claim_one(self):
        platform_app.db.create_user("legacy", "Legacy", None)  # 從舊版升級：有帳號、沒有金鑰
        platform_app.db.add_membership("default", "legacy")
        res = self.join("legacy", make_invite())
        self.assertEqual(res.status_code, 200)
        self.assertIn("token", res.get_json())

    def test_rate_limit_on_bad_codes(self):
        for i in range(platform_app.JOIN_FAIL_LIMIT_PER_IP):
            self.assertEqual(self.join(f"x{i}", "BADCODE123").status_code, 404)
        res = self.join("x99", make_invite())
        self.assertEqual(res.status_code, 429)
        platform_app.reset_join_limiter()
        self.assertEqual(self.join("x99", make_invite()).status_code, 200)

    def test_failed_join_refunds_invite(self):
        code = make_invite(max_uses=1)
        with mock.patch.object(platform_app.db, "add_membership", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):  # TESTING 模式會把例外丟出來；正式環境是 500
                self.client.post("/join", json={"userId": "r1", "code": code})
        self.assertEqual(platform_app.db.get_invite(code)["uses"], 0)


class TestKeys(Base):
    def test_every_app_endpoint_rejects_missing_or_wrong_key(self):
        make_user("u1")
        calls = [
            ("get", "/me?userId=u1", None),
            ("post", "/profile", {"userId": "u1", "displayName": "x"}),
            ("post", "/block", {"userId": "u1", "botId": "default", "blocked": True}),
            ("post", "/leave", {"userId": "u1", "botId": "default"}),
            ("get", "/history?userId=u1&botId=default", None),
            ("get", "/richmenu/current?userId=u1&botId=default", None),
        ]
        for method, path, body in calls:
            for headers in ({}, {"X-LocalBot-Token": "lbu_wrong"}):
                res = getattr(self.client, method)(path, headers=headers, **({"json": body} if body else {}))
                self.assertEqual(res.status_code, 401, (path, headers))

    def test_one_users_key_cannot_act_as_another(self):
        make_user("u1")
        make_user("u2")
        res = self.client.get("/me?userId=u2", headers=app_headers("u1"))
        self.assertEqual(res.status_code, 401)

    def test_revoked_key_is_rejected_everywhere(self):
        make_user("u1")
        h = app_headers("u1")
        platform_app.db.revoke_user_token("u1")
        self.assertEqual(self.client.get("/me?userId=u1", headers=h).status_code, 401)
        body = json.dumps({"destination": "default", "events": [{
            "type": "message", "replyToken": "r", "source": {"type": "user", "userId": "u1"},
            "message": {"id": "m", "type": "text", "text": "x"}}]})
        self.assertEqual(self.client.post("/callback", data=body, headers=h).status_code, 401)
        sc = platform_app.socketio.test_client(platform_app.app, auth={"userId": "u1", "token": h["X-LocalBot-Token"]})
        self.assertFalse(sc.is_connected())

    def test_callback_to_other_bot_requires_membership(self):
        make_bot("shop")
        make_user("u1")  # 只加入 default
        body = json.dumps({"destination": "shop", "events": [{
            "type": "message", "replyToken": "r", "source": {"type": "user", "userId": "u1"},
            "message": {"id": "m", "type": "text", "text": "x"}}]})
        self.assertEqual(self.client.post("/callback", data=body, headers=app_headers("u1")).status_code, 403)
        # 不能替別人傳訊息
        make_user("u2")
        body2 = body.replace('"u1"', '"u2"').replace('"shop"', '"default"')
        self.assertEqual(self.client.post("/callback", data=body2, headers=app_headers("u1")).status_code, 401)

    def test_callback_to_disabled_or_unknown_bot(self):
        make_bot("shop")
        make_user("u1", bots=("default", "shop"))
        platform_app.db.update_bot("shop", enabled=False)
        for dest in ("shop", "ghost", None):
            body = json.dumps({"destination": dest, "events": [{
                "type": "message", "replyToken": "r", "source": {"type": "user", "userId": "u1"},
                "message": {"id": "m", "type": "text", "text": "x"}}]})
            self.assertIn(self.client.post("/callback", data=body, headers=app_headers("u1")).status_code, (400, 404), dest)

    def test_me_and_profile(self):
        make_bot("shop", name="商店")
        make_bot("hidden")
        make_user("u1", bots=("default", "shop", "hidden"), name="Old")
        platform_app.db.update_bot("hidden", enabled=False)
        platform_app.db.save_message("shop", "m1", "u1", "outgoing", "text", {"type": "text", "text": "hi"})
        data = self.client.get("/me?userId=u1", headers=app_headers("u1")).get_json()
        self.assertEqual(sorted(b["botId"] for b in data["bots"]), ["default", "shop"])
        shop = next(b for b in data["bots"] if b["botId"] == "shop")
        self.assertEqual(shop["name"], "商店")
        self.assertIsNotNone(shop["lastMessageAt"])
        self.assertNotIn("secret", json.dumps(data).lower())
        self.assertNotIn("webhook", json.dumps(data).lower())
        res = self.client.post("/profile", json={"userId": "u1", "displayName": " 新名字 "}, headers=app_headers("u1"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(platform_app.db.get_user("u1")["display_name"], "新名字")
        self.assertEqual(self.client.post("/profile", json={"userId": "u1", "displayName": ""},
                                          headers=app_headers("u1")).status_code, 400)

    def test_history_is_per_bot_and_requires_membership(self):
        make_bot("shop")
        make_user("u1", bots=("default", "shop"))
        platform_app.db.save_message("shop", "m1", "u1", "outgoing", "text", {"type": "text", "text": "shop"})
        platform_app.db.save_message("default", "m2", "u1", "outgoing", "text", {"type": "text", "text": "main"})
        h = app_headers("u1")
        get = lambda b: self.client.get(f"/history?userId=u1&botId={b}", headers=h)  # noqa: E731
        self.assertEqual([m["message_id"] for m in get("shop").get_json()["messages"]], ["m1"])
        self.assertEqual([m["message_id"] for m in get("default").get_json()["messages"]], ["m2"])
        make_bot("third")
        self.assertEqual(get("third").status_code, 404)

    def test_offline_messages_are_tagged_with_bot(self):
        make_bot("shop", name="商店")
        make_user("u1", bots=("default", "shop"))
        platform_app.deliver_to_client("shop", "u1", [{"type": "text", "text": "hi"}])
        queued = platform_app.db.pop_offline_messages("u1")
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["botId"], "shop")


class TestBotApiIdentity(Base):
    def test_default_bot_seeded_from_config(self):
        bot = platform_app.db.get_bot("default")
        self.assertEqual(bot["channel_secret"], cfg.CHANNEL_SECRET)
        self.assertEqual(bot["channel_access_token"], cfg.CHANNEL_ACCESS_TOKEN)
        self.assertEqual(bot["webhook_url"], cfg.BOT_WEBHOOK_URL)
        # 舊版 Bot 程式的 token 仍然有效，而且就是預設 Bot
        self.assertEqual(self.client.get("/v2/bot/message/quota", headers=BOT_HEADERS).status_code, 200)
        platform_app.ensure_default_bot()  # 不會重複建立
        self.assertEqual(len(platform_app.db.list_bots()), 1)

    def test_seed_not_repeated_after_default_bot_deleted(self):
        make_bot("shop")
        platform_app.db.delete_bot("default")
        platform_app.ensure_default_bot()
        self.assertEqual([b["bot_id"] for b in platform_app.db.list_bots()], ["shop"])

    def test_each_bot_token_resolves_to_its_own_bot(self):
        _, h1 = make_bot("b1")
        _, h2 = make_bot("b2")
        make_user("u1", bots=("b1",))
        with mock.patch.object(platform_app.socketio, "emit"):
            ok = self.client.post("/v2/bot/message/push", headers=h1, json={"to": "u1", "messages": [{"type": "text", "text": "x"}]})
            self.assertEqual(ok.status_code, 200)
            bad = self.client.post("/v2/bot/message/push", headers=h2, json={"to": "u1", "messages": [{"type": "text", "text": "x"}]})
            self.assertEqual(bad.status_code, 400)
        self.assertEqual(len(platform_app.db.get_messages("b1", "u1")), 1)
        self.assertEqual(platform_app.db.get_messages("b2", "u1"), [])
        self.assertEqual(self.client.get("/v2/bot/message/quota", headers={"Authorization": "Bearer nope"}).status_code, 401)


class AdminBase(Base):
    def setUp(self):
        super().setUp()
        self.csrf = self.client.post("/admin/api/login", json={"password": cfg.ADMIN_PASSWORD}).get_json()["csrf"]

    def call(self, method, path, body=None):
        kw = {"json": body} if body is not None else {}
        return getattr(self.client, method)("/admin/api" + path, headers={"X-CSRF-Token": self.csrf}, **kw)


class TestBotAdmin(AdminBase):
    def test_create_list_update(self):
        res = self.call("post", "/bots", {"name": "客服 Bot", "description": "說明", "webhookUrl": "https://bot.example/hook"})
        self.assertEqual(res.status_code, 201, res.get_data(as_text=True))
        bot = res.get_json()
        self.assertTrue(bot["botId"].startswith("bot-"))
        self.assertTrue(bot["channelSecret"] and bot["channelAccessToken"])
        listing = self.call("get", "/bots").get_json()
        self.assertEqual([b["botId"] for b in listing["bots"]], ["default", bot["botId"]])
        text = json.dumps(listing)
        self.assertNotIn(bot["channelSecret"], text)       # 清單不含金鑰
        self.assertNotIn(bot["channelAccessToken"], text)
        self.assertNotIn(cfg.CHANNEL_SECRET, text)
        # 新 Bot 的 token 馬上能用
        h = {"Authorization": f"Bearer {bot['channelAccessToken']}"}
        self.assertEqual(self.client.get("/v2/bot/message/quota", headers=h).status_code, 200)
        # 更新
        res = self.call("patch", f"/bots/{bot['botId']}", {"name": "新名稱", "webhookUrl": "http://x.example/y", "enabled": False})
        self.assertEqual(res.status_code, 200)
        self.assertEqual((res.get_json()["name"], res.get_json()["enabled"]), ("新名稱", False))
        self.assertEqual(self.client.get("/v2/bot/message/quota", headers=h).status_code, 401)  # 停用後金鑰無效
        self.assertEqual(self.call("patch", f"/bots/{bot['botId']}", {}).status_code, 400)
        self.assertEqual(self.call("patch", "/bots/ghost", {"name": "x"}).status_code, 404)

    def test_create_validation(self):
        base = {"name": "B", "webhookUrl": "https://bot.example/hook"}
        for patch in ({"name": ""}, {"name": "x" * 61}, {"webhookUrl": "ftp://x"}, {"webhookUrl": "not a url"},
                      {"webhookUrl": ""}, {"botId": "a b"}, {"botId": "x" * 33}, {"description": "x" * 201}):
            self.assertEqual(self.call("post", "/bots", dict(base, **patch)).status_code, 400, patch)
        self.assertEqual(self.call("post", "/bots", dict(base, botId="shop")).status_code, 201)
        self.assertEqual(self.call("post", "/bots", dict(base, botId="shop")).status_code, 409)

    def test_secrets_need_password(self):
        make_bot("shop")
        path = "/bots/shop/secrets/CHANNEL_SECRET"
        self.assertEqual(self.call("post", path + "/reveal", {"password": "bad"}).status_code, 403)
        res = self.call("post", path + "/reveal", {"password": cfg.ADMIN_PASSWORD})
        self.assertEqual(res.get_json()["value"], "secret-shop")
        self.assertEqual(self.call("post", "/bots/shop/secrets/APP_SECRET/reveal", {"password": cfg.ADMIN_PASSWORD}).status_code, 404)
        # 重新產生：要密碼 + confirm；舊 token 立刻失效
        body = {"password": cfg.ADMIN_PASSWORD}
        self.assertEqual(self.call("post", "/bots/shop/secrets/CHANNEL_ACCESS_TOKEN/regenerate", body).status_code, 400)
        old = {"Authorization": "Bearer token-shop"}
        self.assertEqual(self.client.get("/v2/bot/message/quota", headers=old).status_code, 200)
        res = self.call("post", "/bots/shop/secrets/CHANNEL_ACCESS_TOKEN/regenerate", dict(body, confirm=True))
        new = res.get_json()["value"]
        self.assertEqual(self.client.get("/v2/bot/message/quota", headers=old).status_code, 401)
        self.assertEqual(self.client.get("/v2/bot/message/quota", headers={"Authorization": f"Bearer {new}"}).status_code, 200)
        # 重新產生 Channel Secret 不影響其他 Bot
        self.call("post", path + "/regenerate", dict(body, confirm=True))
        self.assertNotEqual(platform_app.db.get_bot("shop")["channel_secret"], "secret-shop")
        self.assertEqual(platform_app.db.get_bot("default")["channel_secret"], cfg.CHANNEL_SECRET)

    def test_secret_attempts_are_rate_limited(self):
        make_bot("shop")
        for _ in range(5):
            self.assertEqual(self.call("post", "/bots/shop/secrets/CHANNEL_SECRET/reveal", {"password": "bad"}).status_code, 403)
        res = self.call("post", "/bots/shop/secrets/CHANNEL_SECRET/reveal", {"password": cfg.ADMIN_PASSWORD})
        self.assertEqual(res.status_code, 429)

    def test_webhook_test_uses_that_bots_url_and_secret(self):
        make_bot("shop", webhook_url="http://shop.invalid/hook")
        ok = mock.Mock(status_code=200)
        with mock.patch.object(platform_app.http_requests, "post", return_value=ok) as post:
            data = self.call("post", "/bots/shop/webhook/test").get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(post.call_args.args[0], "http://shop.invalid/hook")
        from localbot.utils import check_signature
        body = post.call_args.kwargs["data"]
        self.assertEqual(json.loads(body)["destination"], "shop")
        self.assertTrue(check_signature("secret-shop", body, post.call_args.kwargs["headers"]["X-Line-Signature"]))
        with mock.patch.object(platform_app.http_requests, "post", side_effect=ConnectionError("refused")):
            data = self.call("post", "/bots/shop/webhook/test").get_json()
        self.assertFalse(data["ok"])
        self.assertIn("ConnectionError", data["error"])

    def test_delete_needs_password_and_confirm_and_removes_only_that_bot(self):
        make_bot("shop")
        make_user("u1", bots=("default", "shop"))
        platform_app.db.save_message("shop", "m1", "u1", "outgoing", "text", {"type": "text", "text": "x"})
        make_invite("shop")
        self.assertEqual(self.call("delete", "/bots/shop", {"password": "bad", "confirm": True}).status_code, 403)
        self.assertEqual(self.call("delete", "/bots/shop", {"password": cfg.ADMIN_PASSWORD}).status_code, 400)
        res = self.call("delete", "/bots/shop", {"password": cfg.ADMIN_PASSWORD, "confirm": True})
        self.assertEqual(res.get_json(), {"deleted": True, "members": 1})
        self.assertIsNone(platform_app.db.get_bot("shop"))
        self.assertEqual(platform_app.db.list_invites("shop"), [])
        self.assertEqual(platform_app.db.get_messages("shop", "u1"), [])
        self.assertTrue(platform_app.db.is_member("default", "u1"))
        self.assertIsNotNone(platform_app.db.get_user("u1"))
        # 這個 Bot 的金鑰立刻失效
        self.assertEqual(self.client.get("/v2/bot/message/quota", headers={"Authorization": "Bearer token-shop"}).status_code, 401)
        self.assertEqual(self.call("delete", "/bots/shop", {"password": cfg.ADMIN_PASSWORD, "confirm": True}).status_code, 404)

    def test_member_counts(self):
        make_bot("shop")
        make_user("a", bots=("default", "shop"))
        make_user("b", bots=("shop",), blocked=True)
        make_invite("shop")
        by_id = {b["botId"]: b for b in self.call("get", "/bots").get_json()["bots"]}
        self.assertEqual((by_id["shop"]["memberCount"], by_id["shop"]["blockedCount"], by_id["shop"]["activeInvites"]), (2, 1, 1))
        self.assertEqual((by_id["default"]["memberCount"], by_id["default"]["activeInvites"]), (1, 0))


class TestInviteAdmin(AdminBase):
    def test_create_and_link(self):
        res = self.call("post", "/invites", {"botId": "default", "label": "給小明", "maxUses": 3, "expiresInHours": 24})
        self.assertEqual(res.status_code, 201, res.get_data(as_text=True))
        inv = res.get_json()
        self.assertEqual(len(inv["code"]), 10)
        self.assertRegex(inv["display"], r"^[A-Z2-9]{5}-[A-Z2-9]{5}$")
        self.assertEqual((inv["status"], inv["maxUses"], inv["uses"], inv["label"]), ("active", 3, 0, "給小明"))
        self.assertAlmostEqual(inv["expiresAt"], time.time() * 1000 + 24 * 3600_000, delta=5000)
        link = urlparse(inv["link"])
        self.assertEqual((link.scheme, link.netloc), ("localbot", "join"))
        q = parse_qs(link.query)
        self.assertEqual(q["code"], [inv["code"]])
        self.assertEqual(q["server"], [platform_app.SERVER_URL.rstrip("/")])
        # 邀請碼真的能用
        res = self.client.post("/join", json={"userId": "fresh", "code": inv["display"]})
        self.assertEqual(res.status_code, 200)

    def test_defaults_and_validation(self):
        inv = self.call("post", "/invites", {"botId": "default"}).get_json()
        self.assertEqual(inv["maxUses"], 1)
        self.assertAlmostEqual(inv["expiresAt"], time.time() * 1000 + 7 * 24 * 3600_000, delta=5000)
        never = self.call("post", "/invites", {"botId": "default", "expiresInHours": None}).get_json()
        self.assertIsNone(never["expiresAt"])
        for patch in ({"botId": None}, {"botId": "ghost"}, {"maxUses": 0}, {"maxUses": 1001}, {"maxUses": True},
                      {"maxUses": "2"}, {"expiresInHours": 0}, {"expiresInHours": -1}, {"expiresInHours": 24 * 366},
                      {"label": "x" * 61}):
            res = self.call("post", "/invites", dict({"botId": "default"}, **patch))
            self.assertIn(res.status_code, (400, 404), patch)

    def test_list_status_revoke_delete(self):
        make_bot("shop", name="商店")
        a = make_invite("default", max_uses=1)
        b = make_invite("shop", expires_at=int(time.time() * 1000) - 1000)
        c = make_invite("shop", max_uses=1)
        platform_app.db.consume_invite(c)
        d = make_invite("shop")
        invites = {i["code"]: i for i in self.call("get", "/invites").get_json()["invites"]}
        self.assertEqual({k: v["status"] for k, v in invites.items()}, {a: "active", b: "expired", c: "used_up", d: "active"})
        self.assertEqual(invites[d]["botName"], "商店")
        self.assertEqual({i["code"] for i in self.call("get", "/invites?botId=shop").get_json()["invites"]}, {b, c, d})
        self.assertEqual(self.call("get", "/invites?botId=ghost").status_code, 404)
        self.assertEqual(self.call("post", f"/invites/{d}/revoke").status_code, 200)
        status = {i["code"]: i["status"] for i in self.call("get", "/invites").get_json()["invites"]}
        self.assertEqual(status[d], "revoked")
        self.assertEqual(self.client.post("/join", json={"userId": "z", "code": d}).status_code, 404)
        self.assertEqual(self.call("delete", f"/invites/{d}").status_code, 200)
        self.assertEqual(self.call("delete", f"/invites/{d}").status_code, 404)
        self.assertEqual(self.call("post", "/invites/NOPE/revoke").status_code, 404)

    def test_requires_csrf(self):
        res = self.client.post("/admin/api/invites", json={"botId": "default"})
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()
