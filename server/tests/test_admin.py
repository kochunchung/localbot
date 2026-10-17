"""
測試：管理後台（/admin）。
"""
import os
import unittest
from unittest import mock

import admin_panel
import localconfig as cfg
from helpers import BOT_HEADERS, app_headers, fresh_db, make_bot, make_invite, make_user, platform_app

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
MENU = {
    "size": {"width": 2500, "height": 843}, "selected": True, "name": "測試選單", "chatBarText": "選單",
    "areas": [{"bounds": {"x": 0, "y": 0, "width": 2500, "height": 843},
               "action": {"type": "message", "text": "hi"}}],
}


class AdminBase(unittest.TestCase):
    def setUp(self):
        fresh_db(f"admin_{self._testMethodName}")
        platform_app.app.config["TESTING"] = True
        admin_panel.reset_login_limiter()
        self.client = platform_app.app.test_client()
        self.events = []
        p = mock.patch.object(platform_app, "send_platform_event",
                              side_effect=lambda bot_id, uid, typ, **kw: self.events.append((uid, typ, kw, bot_id)))
        p.start()
        self.addCleanup(p.stop)

    def login(self, client=None, password=None):
        client = client or self.client
        res = client.post("/admin/api/login", json={"password": password or cfg.ADMIN_PASSWORD})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json()["csrf"]

    def hdr(self, csrf):
        return {"X-CSRF-Token": csrf}

    def add_user(self, uid, name="User", bots=("default",)):
        make_user(uid, bots=bots, name=name)


class TestUiStatic(unittest.TestCase):
    """前端的安全守則（CSP 不允許 inline style / inline 事件；資料一律不可用 innerHTML 輸出）。"""

    def setUp(self):
        with open(os.path.join(cfg.BASE_DIR, "admin_ui", "index.html"), encoding="utf-8") as f:
            self.html = f.read()

    def test_no_inner_html(self):
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(banned, self.html, banned)

    def test_no_inline_handlers_or_style_attributes(self):
        import re
        markup = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", self.html)
        self.assertIsNone(re.search(r"\son[a-z]+\s*=", markup), "inline event handler")
        self.assertIsNone(re.search(r"\sstyle\s*=", markup), "inline style attribute")
        self.assertIsNone(re.search(r"<(script|link)[^>]+(src|href)=\"https?:", self.html), "external resource")
        self.assertEqual(self.html.count('nonce="__NONCE__"'), 2)  # 一個 <style>、一個 <script>


class TestAuth(AdminBase):
    def test_page_has_csp_nonce(self):
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)
        csp = res.headers["Content-Security-Policy"]
        nonce = csp.split("script-src 'nonce-")[1].split("'")[0]
        body = res.get_data(as_text=True)
        self.assertIn(nonce, body)
        self.assertNotIn("__NONCE__", body)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(res.headers["X-Frame-Options"], "DENY")
        self.assertEqual(res.headers["Cache-Control"], "no-store")

    def test_api_requires_login(self):
        for method, path in (("get", "/admin/api/stats"), ("get", "/admin/api/users"),
                             ("post", "/admin/api/send"), ("get", "/admin/api/settings"),
                             ("get", "/admin/api/richmenus?botId=default"), ("get", "/admin/api/bots"),
                             ("post", "/admin/api/bots"), ("get", "/admin/api/invites"),
                             ("post", "/admin/api/invites"), ("post", "/admin/api/users/u1/revoke")):
            res = getattr(self.client, method)(path)
            self.assertEqual(res.status_code, 401, path)

    def test_login_wrong_then_right(self):
        self.assertEqual(self.client.post("/admin/api/login", json={"password": "nope"}).status_code, 401)
        self.assertEqual(self.client.post("/admin/api/login", json={}).status_code, 401)
        self.assertEqual(self.client.post("/admin/api/login", json={"password": 123}).status_code, 401)
        csrf = self.login()
        info = self.client.get("/admin/api/session").get_json()
        self.assertEqual(info, {"authenticated": True, "csrf": csrf})
        self.assertEqual(self.client.get("/admin/api/stats").status_code, 200)

    def test_cookie_flags(self):
        res = self.client.post("/admin/api/login", json={"password": cfg.ADMIN_PASSWORD})
        cookie = res.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Path=/admin", cookie)

    def test_login_rate_limit(self):
        for _ in range(5):
            self.assertEqual(self.client.post("/admin/api/login", json={"password": "x"}).status_code, 401)
        res = self.client.post("/admin/api/login", json={"password": cfg.ADMIN_PASSWORD})
        self.assertEqual(res.status_code, 429)
        self.assertGreater(int(res.headers["Retry-After"]), 0)

    def test_csrf_required_for_writes(self):
        csrf = self.login()
        self.add_user("u1")
        body = {"botId": "default", "target": "user", "userId": "u1", "text": "hi"}
        self.assertEqual(self.client.post("/admin/api/send", json=body).status_code, 403)
        self.assertEqual(self.client.post("/admin/api/send", json=body, headers={"X-CSRF-Token": "bad"}).status_code, 403)
        with mock.patch.object(platform_app, "deliver_to_client", return_value=["m1"]):
            self.assertEqual(self.client.post("/admin/api/send", json=body, headers=self.hdr(csrf)).status_code, 200)

    def test_session_expiry(self):
        self.login()
        with self.client.session_transaction() as sess:
            sess["iat"] = 0
        self.assertEqual(self.client.get("/admin/api/stats").status_code, 401)
        self.assertFalse(self.client.get("/admin/api/session").get_json()["authenticated"])

    def test_logout(self):
        csrf = self.login()
        self.assertEqual(self.client.post("/admin/api/logout", headers=self.hdr(csrf)).status_code, 200)
        self.assertEqual(self.client.get("/admin/api/stats").status_code, 401)


class TestDashboardAndUsers(AdminBase):
    def test_stats(self):
        self.login()
        self.add_user("u1", "小明")
        self.add_user("u2", "Bob")
        platform_app.db.set_blocked("default", "u2", True)
        platform_app.db.save_message("default", "m1", "u1", "incoming", "text", {"type": "text", "text": "hi"})
        platform_app.db.save_message("default", "m2", "u1", "outgoing", "text", {"type": "text", "text": "yo"})
        with mock.patch.dict(platform_app.connected_users, {"u1": {"sid1"}}, clear=True):
            data = self.client.get("/admin/api/stats").get_json()
        self.assertEqual((data["users"], data["blockedUsers"], data["online"]), (2, 1, 1))
        self.assertEqual((data["messagesIncoming"], data["messagesOutgoing"], data["messagesLast24h"]), (1, 1, 2))
        self.assertEqual(len(data["daily"]), 7)
        self.assertEqual(data["daily"][-1]["incoming"], 1)
        self.assertEqual(data["daily"][-1]["outgoing"], 1)

    def test_users_list_search_detail(self):
        self.login()
        self.add_user("alice_1", "愛麗絲")
        self.add_user("bob", "Bob")
        platform_app.db.save_message("default", "m1", "alice_1", "incoming", "text", {"type": "text", "text": "hi"})
        data = self.client.get("/admin/api/users").get_json()
        self.assertEqual(data["total"], 2)
        found = self.client.get("/admin/api/users?q=愛麗").get_json()
        self.assertEqual([u["userId"] for u in found["users"]], ["alice_1"])
        self.assertEqual(found["users"][0]["messageCount"], 1)
        # LIKE 萬用字元要被跳脫
        self.assertEqual(self.client.get("/admin/api/users?q=%25").get_json()["total"], 0)
        detail = self.client.get("/admin/api/users/alice_1").get_json()
        self.assertEqual(detail["displayName"], "愛麗絲")
        self.assertEqual(self.client.get("/admin/api/users/nobody").status_code, 404)
        self.assertEqual(self.client.get("/admin/api/users/..%2Fx").status_code, 404)

    def test_update_rename_and_block(self):
        csrf = self.login()
        self.add_user("u1", "Old")
        res = self.client.patch("/admin/api/users/u1", json={"displayName": "  New  "}, headers=self.hdr(csrf))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(platform_app.db.get_user("u1")["display_name"], "New")
        self.assertEqual(self.client.patch("/admin/api/users/u1", json={"displayName": ""}, headers=self.hdr(csrf)).status_code, 400)
        self.assertEqual(self.client.patch("/admin/api/users/u1", json={"blocked": "yes", "botId": "default"}, headers=self.hdr(csrf)).status_code, 400)
        self.assertEqual(self.client.patch("/admin/api/users/u1", json={"blocked": True}, headers=self.hdr(csrf)).status_code, 404)  # 沒指定 Bot
        block = {"blocked": True, "botId": "default"}
        self.client.patch("/admin/api/users/u1", json=block, headers=self.hdr(csrf))
        self.client.patch("/admin/api/users/u1", json=block, headers=self.hdr(csrf))  # 重複不再送事件
        self.assertTrue(platform_app.db.is_blocked("default", "u1"))
        self.client.patch("/admin/api/users/u1", json={"blocked": False, "botId": "default"}, headers=self.hdr(csrf))
        self.assertEqual([(e[0], e[1], e[3]) for e in self.events],
                         [("u1", "unfollow", "default"), ("u1", "follow", "default")])
        self.assertEqual(self.events[1][2], {"follow": {"isUnblocked": True}})

    def test_block_is_per_bot(self):
        csrf = self.login()
        make_bot("shop")
        self.add_user("u1", bots=("default", "shop"))
        self.client.patch("/admin/api/users/u1", json={"blocked": True, "botId": "shop"}, headers=self.hdr(csrf))
        self.assertTrue(platform_app.db.is_blocked("shop", "u1"))
        self.assertFalse(platform_app.db.is_blocked("default", "u1"))
        bots = {b["botId"]: b["blocked"] for b in self.client.get("/admin/api/users/u1").get_json()["bots"]}
        self.assertEqual(bots, {"default": False, "shop": True})

    def test_revoke_key_only_affects_that_user(self):
        csrf = self.login()
        self.add_user("u1")
        self.add_user("u2")
        h1, h2 = app_headers("u1"), app_headers("u2")
        self.assertEqual(self.client.post("/admin/api/users/u1/revoke", json={}, headers=self.hdr(csrf)).status_code, 400)
        with mock.patch.object(platform_app, "disconnect_user") as disc:
            res = self.client.post("/admin/api/users/u1/revoke", json={"confirm": True}, headers=self.hdr(csrf))
        self.assertEqual(res.status_code, 200)
        disc.assert_called_once_with("u1")
        self.assertEqual(self.client.get("/me?userId=u1", headers=h1).status_code, 401)
        self.assertEqual(self.client.get("/me?userId=u2", headers=h2).status_code, 200)
        users = {u["userId"]: u for u in self.client.get("/admin/api/users").get_json()["users"]}
        self.assertEqual((users["u1"]["keyStatus"], users["u2"]["keyStatus"]), ("revoked", "active"))
        # 重新用邀請碼加入 → 領到新金鑰，舊金鑰仍無效
        res = self.client.post("/join", json={"userId": "u1", "code": make_invite()})
        self.assertEqual(res.status_code, 200)
        new_token = res.get_json()["token"]
        self.assertEqual(self.client.get("/me?userId=u1", headers=h1).status_code, 401)
        self.assertEqual(self.client.get("/me?userId=u1", headers={"X-LocalBot-Token": new_token}).status_code, 200)

    def test_remove_user_from_bot(self):
        csrf = self.login()
        make_bot("shop")
        self.add_user("u1", bots=("default", "shop"))
        platform_app.db.save_message("shop", "m1", "u1", "incoming", "text", {"type": "text", "text": "x"})
        res = self.client.delete("/admin/api/users/u1/bots/shop", headers=self.hdr(csrf))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(platform_app.db.is_member("shop", "u1"))
        self.assertTrue(platform_app.db.is_member("default", "u1"))
        self.assertEqual(platform_app.db.get_messages("shop", "u1"), [])
        self.assertEqual([(e[1], e[3]) for e in self.events], [("unfollow", "shop")])
        self.assertEqual(self.client.delete("/admin/api/users/u1/bots/shop", headers=self.hdr(csrf)).status_code, 404)

    def test_users_filter_by_bot(self):
        self.login()
        make_bot("shop")
        self.add_user("a")
        self.add_user("b", bots=("shop",))
        self.add_user("c", bots=("default", "shop"))
        ids = lambda qs: sorted(u["userId"] for u in self.client.get("/admin/api/users" + qs).get_json()["users"])  # noqa: E731
        self.assertEqual(ids(""), ["a", "b", "c"])
        self.assertEqual(ids("?botId=shop"), ["b", "c"])
        self.assertEqual(ids("?botId=default"), ["a", "c"])
        self.assertEqual(self.client.get("/admin/api/users?botId=nope").status_code, 404)

    def test_delete_user_removes_data(self):
        csrf = self.login()
        self.add_user("u1")
        self.add_user("u2")
        platform_app.db.save_message("default", "m1", "u1", "incoming", "text", {"type": "text", "text": "x"})
        platform_app.db.enqueue_offline_message("default", "u1", {"a": 1})
        platform_app.db.save_reply_token("default", "tok", "u1")
        res = self.client.delete("/admin/api/users/u1", headers=self.hdr(csrf))
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(platform_app.db.get_user("u1"))
        self.assertEqual(platform_app.db.get_messages("default", "u1"), [])
        self.assertEqual(platform_app.db.pop_offline_messages("u1"), [])
        self.assertIsNone(platform_app.db.get_user_by_reply_token("default", "tok"))
        self.assertFalse(platform_app.db.is_member("default", "u1"))
        self.assertIsNotNone(platform_app.db.get_user("u2"))
        self.assertEqual(self.client.delete("/admin/api/users/u1", headers=self.hdr(csrf)).status_code, 404)


class TestMessages(AdminBase):
    def setUp(self):
        super().setUp()
        self.csrf = self.login()
        self.add_user("u1", "小明")
        self.add_user("u10", "Other")
        db = platform_app.db
        db.save_message("default", "a", "u1", "incoming", "text", {"type": "text", "text": "你好 100%"})
        db.save_message("default", "b", "u1", "outgoing", "image", {
            "type": "image", "originalContentUrl": "https://x.example/media/pic.jpg",
            "previewImageUrl": "https://evil.example/other.png"})
        db.save_message("default", "c", "u1", "outgoing", "flex", {"type": "flex", "altText": "卡片", "contents": {}})
        db.save_message("default", "d", "u10", "incoming", "postback", {"data": "action=buy"})
        db.save_message("default", "e", "u1", "outgoing", "sticker", {"type": "sticker", "packageId": "1", "stickerId": "2"})

    def test_search_filters(self):
        get = lambda qs: self.client.get("/admin/api/messages" + qs).get_json()  # noqa: E731
        self.assertEqual(len(get("")["messages"]), 5)
        self.assertEqual([m["messageId"] for m in get("?q=100%25")["messages"]], ["a"])
        self.assertEqual(len(get("?direction=incoming")["messages"]), 2)
        self.assertEqual([m["messageId"] for m in get("?type=flex")["messages"]], ["c"])
        self.assertEqual(len(get("?user=小明")["messages"]), 4)
        self.assertEqual(len(get("?user=u1")["messages"]), 5)  # 模糊比對：u1 與 u10

    def test_pagination(self):
        page1 = self.client.get("/admin/api/messages?limit=2").get_json()
        self.assertEqual(len(page1["messages"]), 2)
        self.assertTrue(page1["hasMore"])
        page2 = self.client.get(f"/admin/api/messages?limit=2&beforeId={page1['messages'][-1]['id']}").get_json()
        self.assertEqual(len(page2["messages"]), 2)
        page3 = self.client.get(f"/admin/api/messages?limit=2&beforeId={page2['messages'][-1]['id']}").get_json()
        self.assertEqual(len(page3["messages"]), 1)
        self.assertFalse(page3["hasMore"])

    def test_summary_and_thumb(self):
        by_id = {m["messageId"]: m for m in self.client.get("/admin/api/messages").get_json()["messages"]}
        self.assertEqual(by_id["a"]["summary"], "你好 100%")
        self.assertEqual(by_id["a"]["displayName"], "小明")
        self.assertEqual(by_id["b"]["summary"], "[圖片]")
        self.assertEqual(by_id["b"]["thumb"], "/media/pic.jpg")  # 只取本機 /media/ 路徑
        self.assertEqual(by_id["c"]["summary"], "[flex] 卡片")
        self.assertEqual(by_id["d"]["summary"], "[Postback] action=buy")
        self.assertEqual(by_id["e"]["summary"], "[貼圖] 1/2")

    def test_user_messages_exact_user(self):
        data = self.client.get("/admin/api/users/u1/messages").get_json()
        self.assertEqual(len(data["messages"]), 4)  # 不含 u10
        self.assertTrue(all(m["userId"] == "u1" for m in data["messages"]))
        self.assertEqual(self.client.get("/admin/api/users/zzz/messages").status_code, 404)

    def test_filter_by_bot(self):
        make_bot("shop", name="商店")
        platform_app.db.save_message("shop", "s1", "u1", "outgoing", "text", {"type": "text", "text": "shop msg"})
        data = self.client.get("/admin/api/messages?botId=shop").get_json()
        self.assertEqual([(m["messageId"], m["botId"], m["botName"]) for m in data["messages"]], [("s1", "shop", "商店")])
        self.assertEqual(len(self.client.get("/admin/api/messages").get_json()["messages"]), 6)
        self.assertEqual(len(self.client.get("/admin/api/messages?botId=default").get_json()["messages"]), 5)
        self.assertEqual(self.client.get("/admin/api/messages?botId=nope").status_code, 404)
        self.assertEqual(len(self.client.get("/admin/api/users/u1/messages?botId=shop").get_json()["messages"]), 1)


class TestSend(AdminBase):
    def setUp(self):
        super().setUp()
        self.csrf = self.login()
        self.add_user("u1")
        self.add_user("u2")

    def post(self, body):
        body = dict(body)
        body.setdefault("botId", "default")
        return self.client.post("/admin/api/send", json=body, headers=self.hdr(self.csrf))

    def test_send_to_user(self):
        with mock.patch.object(platform_app, "deliver_to_client", return_value=["m1"]) as d:
            res = self.post({"target": "user", "userId": "u1", "text": "哈囉"})
        self.assertEqual(res.get_json(), {"sent": 1, "messageIds": ["m1"]})
        d.assert_called_once_with("default", "u1", [{"type": "text", "text": "哈囉"}])

    def test_send_validation(self):
        self.assertEqual(self.post({"target": "user", "userId": "u1", "text": "  "}).status_code, 400)
        self.assertEqual(self.post({"target": "user", "userId": "u1", "text": "x" * 5001}).status_code, 400)
        self.assertEqual(self.post({"target": "user", "userId": "ghost", "text": "x"}).status_code, 404)
        self.assertEqual(self.post({"target": "other", "text": "x"}).status_code, 400)
        self.assertEqual(self.post({"target": "user", "userId": "u1", "text": "x", "botId": None}).status_code, 400)
        self.assertEqual(self.post({"target": "user", "userId": "u1", "text": "x", "botId": "nope"}).status_code, 404)

    def test_send_requires_membership_and_enabled_bot(self):
        make_bot("shop")
        self.assertEqual(self.post({"target": "user", "userId": "u1", "text": "x", "botId": "shop"}).status_code, 404)
        platform_app.db.add_membership("shop", "u1")
        platform_app.db.update_bot("shop", enabled=False)
        self.assertEqual(self.post({"target": "user", "userId": "u1", "text": "x", "botId": "shop"}).status_code, 409)

    def test_broadcast_only_reaches_that_bots_users(self):
        make_bot("shop")
        self.add_user("s1", bots=("shop",))
        with mock.patch.object(platform_app, "deliver_to_client", return_value=["m"]) as d:
            res = self.post({"target": "broadcast", "text": "hi", "botId": "shop", "confirm": True})
        self.assertEqual(res.get_json(), {"sent": 1})
        self.assertEqual([c.args[:2] for c in d.call_args_list], [("shop", "s1")])

    def test_send_to_blocked_user_rejected(self):
        platform_app.db.set_blocked("default", "u1", True)
        self.assertEqual(self.post({"target": "user", "userId": "u1", "text": "x"}).status_code, 409)

    def test_broadcast_needs_confirm_and_skips_blocked(self):
        platform_app.db.set_blocked("default", "u2", True)
        with mock.patch.object(platform_app, "deliver_to_client", return_value=["m"]) as d:
            self.assertEqual(self.post({"target": "broadcast", "text": "all"}).status_code, 400)
            d.assert_not_called()
            res = self.post({"target": "broadcast", "text": "all", "confirm": True})
        self.assertEqual(res.get_json(), {"sent": 1})
        self.assertEqual([c.args[1] for c in d.call_args_list], ["u1"])

    def test_send_really_delivers_and_saves(self):
        self.post({"target": "user", "userId": "u1", "text": "真的送出"})
        msgs = platform_app.db.get_messages("default", "u1")
        self.assertEqual(msgs[-1]["direction"], "outgoing")
        self.assertEqual(msgs[-1]["content"]["text"], "真的送出")
        self.assertEqual(len(platform_app.db.pop_offline_messages("u1")), 1)  # 離線 → 進佇列


class TestRichMenu(AdminBase):
    def setUp(self):
        super().setUp()
        self.csrf = self.login()
        self.add_user("u1")
        self.notified = []
        p = mock.patch.object(platform_app, "notify_richmenu_changed",
                              side_effect=lambda bot_id, ids=None: self.notified.append((bot_id, ids)))
        p.start()
        self.addCleanup(p.stop)

    def call(self, method, path, **kw):
        return getattr(self.client, method)(path, headers=self.hdr(self.csrf), **kw)

    def create(self, bot_id="default"):
        res = self.call("post", "/admin/api/richmenus", json=dict(MENU, botId=bot_id))
        self.assertEqual(res.status_code, 200)
        return res.get_json()["richMenuId"]

    def upload(self, rid, data=PNG, ctype="image/png"):
        return self.call("post", f"/admin/api/richmenus/{rid}/image", data=data, content_type=ctype)

    def test_create_validation(self):
        bad = dict(MENU, botId="default", chatBarText="這個文字實在是太長了一點點不行啊")
        self.assertEqual(self.call("post", "/admin/api/richmenus", json=bad).status_code, 400)
        self.assertEqual(self.call("post", "/admin/api/richmenus", json={}).status_code, 400)
        self.assertEqual(self.call("post", "/admin/api/richmenus", json=dict(MENU)).status_code, 400)  # 沒指定 Bot
        self.assertEqual(self.call("post", "/admin/api/richmenus", json=dict(MENU, botId="nope")).status_code, 404)

    def test_full_flow(self):
        rid = self.create()
        listing = self.call("get", "/admin/api/richmenus?botId=default").get_json()
        self.assertFalse(listing["richmenus"][0]["hasImage"])
        # 沒有圖片不能設為預設 / 綁定
        self.assertEqual(self.call("post", f"/admin/api/richmenus/{rid}/default").status_code, 400)
        self.assertEqual(self.call("post", "/admin/api/users/u1/richmenu", json={"botId": "default", "richMenuId": rid}).status_code, 400)
        # 圖片驗證
        self.assertEqual(self.upload(rid, ctype="text/plain").status_code, 415)
        self.assertEqual(self.upload(rid, data=b"not an image").status_code, 400)
        self.assertEqual(self.upload(rid, data=PNG + b"0" * (1024 * 1024)).status_code, 413)
        self.assertEqual(self.upload(rid).status_code, 200)
        self.assertEqual(self.upload(rid).status_code, 200)  # 後台允許換圖
        img = self.call("get", f"/admin/api/richmenus/{rid}/image")
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img.data, PNG)
        # 預設、綁定
        self.assertEqual(self.call("post", f"/admin/api/richmenus/{rid}/default").status_code, 200)
        self.assertEqual(self.call("post", "/admin/api/users/u1/richmenu", json={"botId": "default", "richMenuId": rid}).status_code, 200)
        listing = self.call("get", "/admin/api/richmenus?botId=default").get_json()
        self.assertEqual(listing["defaultRichMenuId"], rid)
        self.assertTrue(listing["richmenus"][0]["isDefault"])
        self.assertEqual(listing["richmenus"][0]["userCount"], 1)
        self.assertEqual(self.call("get", "/admin/api/users/u1").get_json()["bots"][0]["richMenuId"], rid)
        # 別名
        self.assertEqual(self.call("post", "/admin/api/richmenu-aliases", json={"botId": "default", "aliasId": "a b", "richMenuId": rid}).status_code, 400)
        self.assertEqual(self.call("post", "/admin/api/richmenu-aliases", json={"botId": "default", "aliasId": "main", "richMenuId": rid}).status_code, 200)
        self.assertEqual(self.call("get", "/admin/api/richmenus?botId=default").get_json()["aliases"], [{"aliasId": "main", "richMenuId": rid}])
        self.assertEqual(platform_app.db.get_richmenu_alias("default", "main"), rid)
        # 取消綁定、取消預設、刪除
        self.assertEqual(self.call("delete", "/admin/api/users/u1/richmenu?botId=default").status_code, 200)
        self.assertIsNone(platform_app.db.get_user_richmenu_id("default", "u1"))
        self.assertEqual(self.call("delete", "/admin/api/richmenu-default?botId=default").status_code, 200)
        self.assertIsNone(platform_app.db.get_setting("default_richmenu:default"))
        path = os.path.join(cfg.RICHMENU_DIR, f"{rid}.png")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.call("delete", f"/admin/api/richmenus/{rid}").status_code, 200)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.call("get", "/admin/api/richmenus?botId=default").get_json()["richmenus"], [])
        self.assertEqual(self.call("delete", f"/admin/api/richmenus/{rid}").status_code, 404)
        self.assertTrue(self.notified)  # 有通知 App

    def test_replace_image_with_other_format_removes_old_file(self):
        rid = self.create()
        self.upload(rid)
        jpg = b"\xff\xd8\xff" + b"0" * 32
        self.assertEqual(self.upload(rid, data=jpg, ctype="image/jpeg").status_code, 200)
        self.assertFalse(os.path.exists(os.path.join(cfg.RICHMENU_DIR, f"{rid}.png")))
        self.assertTrue(os.path.exists(os.path.join(cfg.RICHMENU_DIR, f"{rid}.jpg")))
        self.call("delete", f"/admin/api/richmenus/{rid}")

    def test_menus_are_per_bot(self):
        make_bot("shop")
        self.add_user("s1", bots=("shop",))
        d, sh = self.create("default"), self.create("shop")
        self.upload(d)
        self.upload(sh)
        ids = lambda b: [m["richMenuId"] for m in self.call("get", f"/admin/api/richmenus?botId={b}").get_json()["richmenus"]]  # noqa: E731
        self.assertEqual((ids("default"), ids("shop")), ([d], [sh]))
        # 各 Bot 各自的預設
        self.call("post", f"/admin/api/richmenus/{sh}/default")
        self.assertEqual(platform_app.db.get_setting("default_richmenu:shop"), sh)
        self.assertIsNone(platform_app.db.get_setting("default_richmenu:default"))
        self.assertEqual(self.notified[-1][0], "shop")
        # 不能把別的 Bot 的選單綁給使用者 / 設別名
        bind = lambda uid, bot, rid: self.call("post", f"/admin/api/users/{uid}/richmenu", json={"botId": bot, "richMenuId": rid})  # noqa: E731
        self.assertEqual(bind("s1", "shop", d).status_code, 400)
        self.assertEqual(bind("u1", "shop", sh).status_code, 404)  # u1 不是 shop 的好友
        self.assertEqual(bind("s1", "shop", sh).status_code, 200)
        res = self.call("post", "/admin/api/richmenu-aliases", json={"botId": "shop", "aliasId": "x", "richMenuId": d})
        self.assertEqual(res.status_code, 400)
        # 刪除 Bot 會清掉它的選單檔案
        path = os.path.join(cfg.RICHMENU_DIR, f"{sh}.png")
        self.assertTrue(os.path.exists(path))
        res = self.call("delete", "/admin/api/bots/shop", json={"password": cfg.ADMIN_PASSWORD, "confirm": True})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(ids("default"), [d])
        self.call("delete", f"/admin/api/richmenus/{d}")

    def test_bad_ids_rejected(self):
        self.assertEqual(self.call("get", "/admin/api/richmenus/..%2Fetc/image").status_code, 404)
        self.assertEqual(self.call("post", "/admin/api/richmenus/nope/default").status_code, 404)
        self.assertEqual(self.call("delete", "/admin/api/richmenu-aliases/nope?botId=default").status_code, 404)


class TestSettings(AdminBase):
    def setUp(self):
        super().setUp()
        self.csrf = self.login()
        # 這個測試會改管理員密碼：結束後還原，避免影響其他測試檔
        saved = cfg.ADMIN_PASSWORD
        self.addCleanup(lambda: cfg.save_secret("ADMIN_PASSWORD", saved))

    def post(self, path, body):
        return self.client.post(path, json=body, headers=self.hdr(self.csrf))

    def test_settings_has_no_secrets(self):
        res = self.client.get("/admin/api/settings")
        text = res.get_data(as_text=True)
        self.assertNotIn(cfg.ADMIN_PASSWORD, text)
        self.assertNotIn(cfg.CHANNEL_SECRET, text)
        self.assertNotIn(cfg.CHANNEL_ACCESS_TOKEN, text)
        self.assertNotIn("secrets", res.get_json())
        self.assertEqual(res.get_json()["serverUrl"], platform_app.SERVER_URL)

    def test_old_global_secret_endpoints_are_gone(self):
        for name in ("APP_SECRET", "CHANNEL_SECRET"):
            for action in ("reveal", "regenerate"):
                res = self.post(f"/admin/api/secrets/{name}/{action}", {"password": cfg.ADMIN_PASSWORD, "confirm": True})
                self.assertEqual(res.status_code, 404)

    def test_password_change_logs_out_other_sessions(self):
        other = platform_app.app.test_client()
        self.login(other)
        self.assertEqual(other.get("/admin/api/stats").status_code, 200)
        old = cfg.ADMIN_PASSWORD
        self.assertEqual(self.post("/admin/api/password", {"current": "bad", "new": "x" * 12}).status_code, 403)
        self.assertEqual(self.post("/admin/api/password", {"current": old, "new": "short"}).status_code, 400)
        res = self.post("/admin/api/password", {"current": old, "new": "a-brand-new-password"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(cfg.ADMIN_PASSWORD, "a-brand-new-password")
        self.assertEqual(self.client.get("/admin/api/stats").status_code, 200)  # 本機維持登入
        self.assertEqual(other.get("/admin/api/stats").status_code, 401)        # 其他裝置被登出
        admin_panel.reset_login_limiter()
        self.assertEqual(platform_app.app.test_client().post("/admin/api/login", json={"password": old}).status_code, 401)

    def test_password_change_refused_when_set_by_env(self):
        with mock.patch.dict(cfg.SECRET_SOURCES, {"ADMIN_PASSWORD": "env"}):
            res = self.post("/admin/api/password", {"current": cfg.ADMIN_PASSWORD, "new": "a-brand-new-password"})
        self.assertEqual(res.status_code, 409)


if __name__ == "__main__":
    unittest.main()


class TestBotAvatar(AdminBase):
    """3.1：後台上傳 Bot 頭像，App 的 /me、/join 會拿到 avatarUrl。"""

    def setUp(self):
        super().setUp()
        self.csrf = self.login()
        self.add_user("u1")

    def upload(self, data, bot="default"):
        return self.client.post(f"/admin/api/bots/{bot}/avatar", data=data,
                                headers={**self.hdr(self.csrf), "Content-Type": "image/png"})

    def me_avatar(self):
        res = self.client.get("/me?userId=u1", headers=app_headers("u1"))
        return res.get_json()["bots"][0]["avatarUrl"]

    def test_upload_replace_and_delete(self):
        self.assertEqual(self.me_avatar(), "")
        res = self.upload(PNG)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        url = res.get_json()["avatarUrl"]
        self.assertRegex(url, r"^/avatars/default-[0-9a-f]{8}\.png$")
        self.assertEqual(self.me_avatar(), url)
        img = self.client.get(url)
        self.assertEqual((img.status_code, img.data), (200, PNG))
        img.close()
        # 換一張：網址改變，舊檔刪除
        url2 = self.upload(b"\xff\xd8\xff" + b"1" * 32).get_json()["avatarUrl"]
        self.assertTrue(url2.endswith(".jpg"))
        self.assertNotEqual(url, url2)
        self.assertEqual(self.client.get(url).status_code, 404)
        # 刪除
        res = self.client.delete("/admin/api/bots/default/avatar", headers=self.hdr(self.csrf))
        self.assertEqual(res.get_json()["avatarUrl"], "")
        self.assertEqual(self.client.get(url2).status_code, 404)
        self.assertEqual(self.me_avatar(), "")

    def test_rejects_bad_input(self):
        self.assertEqual(self.upload(b"GIF89a....").status_code, 400)
        self.assertEqual(self.upload(b"").status_code, 400)
        self.assertEqual(self.upload(PNG + b"0" * (1024 * 1024)).status_code, 413)
        self.assertEqual(self.upload(PNG, bot="nope").status_code, 404)
        res = self.client.post("/admin/api/bots/default/avatar", data=PNG, headers={"Content-Type": "image/png"})
        self.assertEqual(res.status_code, 403)  # 沒有 CSRF token
        for bad in ("../secrets.json", "x.html", ".hidden.png"):
            self.assertEqual(self.client.get(f"/avatars/{bad}").status_code, 404, bad)

    def test_webp_and_join_response(self):
        webp = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"0" * 16
        url = self.upload(webp).get_json()["avatarUrl"]
        self.assertTrue(url.endswith(".webp"))
        code = make_invite()
        res = self.client.post("/join", json={"userId": "newcomer", "code": code, "displayName": "新朋友"})
        self.assertEqual(res.get_json()["bot"]["avatarUrl"], url)

    def test_delete_bot_removes_avatar(self):
        make_bot("shop")
        url = self.upload(PNG, bot="shop").get_json()["avatarUrl"]
        with mock.patch.object(cfg, "ADMIN_PASSWORD", cfg.ADMIN_PASSWORD):
            res = self.client.delete("/admin/api/bots/shop", json={"password": cfg.ADMIN_PASSWORD, "confirm": True},
                                     headers=self.hdr(self.csrf))
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        self.assertEqual(self.client.get(url).status_code, 404)
