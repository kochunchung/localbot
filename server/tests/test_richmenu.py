"""
測試：Rich Menu（Bot API、App API、v1 / v3 SDK）。
"""
import json
import unittest
from unittest import mock

from helpers import BOT_HEADERS, CHANNEL_ACCESS_TOKEN, app_headers, fresh_db, make_bot, make_user, platform_app

BOT = BOT_HEADERS
PNG = platform_app._demo_imagemap_png(240)


def menu_body(name="main", alias_target=None):
    action = ({"type": "richmenuswitch", "richMenuAliasId": alias_target, "data": "switch"}
              if alias_target else {"type": "message", "text": "左"})
    return {
        "size": {"width": 2500, "height": 843},
        "selected": True,
        "name": name,
        "chatBarText": "選單",
        "areas": [
            {"bounds": {"x": 0, "y": 0, "width": 1250, "height": 843}, "action": action},
            {"bounds": {"x": 1250, "y": 0, "width": 1250, "height": 843},
             "action": {"type": "uri", "uri": "https://example.com"}},
        ],
    }


class _FakeResponse:
    def __init__(self, res):
        self.status_code = res.status_code
        self.reason = res.status
        self.content = res.get_data()
        self.text = self.content.decode("utf-8", errors="replace")
        self.headers = dict(res.headers)

    def json(self):
        return json.loads(self.text)


def route_to(client):
    def request(method, url, json=None, data=None, headers=None, timeout=None, **_):
        path = url.split("://", 1)[-1]
        path = path[path.index("/"):]
        return _FakeResponse(client.open(path, method=method, json=json, data=data, headers=headers))
    return request


class RichMenuBase(unittest.TestCase):
    def setUp(self):
        fresh_db(f"rm_{self._testMethodName}")
        platform_app.app.config["TESTING"] = True
        self.client = platform_app.app.test_client()
        self.emitted = []
        p = mock.patch.object(platform_app.socketio, "emit",
                              side_effect=lambda ev, data, room=None: self.emitted.append((ev, room)))
        p.start()
        self.addCleanup(p.stop)
        platform_app.connected_users.clear()
        platform_app.connected_users.update({"u1": {"s1"}, "u2": {"s2"}})
        self.addCleanup(platform_app.connected_users.clear)
        for uid in ("u1", "u2"):
            make_user(uid)

    def create(self, body=None):
        res = self.client.post("/v2/bot/richmenu", headers=BOT, json=body or menu_body())
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json()["richMenuId"]

    def upload(self, rid, data=PNG, ctype="image/png"):
        return self.client.post(f"/v2/bot/richmenu/{rid}/content", headers={**BOT, "Content-Type": ctype}, data=data)

    def current(self, uid):
        return self.client.get(f"/richmenu/current?userId={uid}&botId=default", headers=app_headers(uid)).get_json()["richMenu"]


class TestRichMenuApi(RichMenuBase):
    def test_validation(self):
        bad = menu_body()
        bad["chatBarText"] = "這個文字超過十四個字元的限制喔喔喔"
        self.assertEqual(self.client.post("/v2/bot/richmenu/validate", headers=BOT, json=bad).status_code, 400)
        bad = menu_body()
        bad["size"] = {"width": 2500, "height": 2500}  # 比例不足 1.45
        self.assertEqual(self.client.post("/v2/bot/richmenu", headers=BOT, json=bad).status_code, 400)
        bad = menu_body()
        bad["areas"][1]["bounds"]["width"] = 2000  # 超出範圍
        self.assertEqual(self.client.post("/v2/bot/richmenu", headers=BOT, json=bad).status_code, 400)
        self.assertEqual(self.client.post("/v2/bot/richmenu/validate", headers=BOT, json=menu_body()).status_code, 200)
        self.assertEqual(self.client.post("/v2/bot/richmenu", json=menu_body()).status_code, 401)

    def test_create_upload_default_and_app_view(self):
        rid = self.create()
        self.assertTrue(rid.startswith("richmenu-"))
        # 尚未上傳圖片不能設為預設
        self.assertEqual(self.client.post(f"/v2/bot/user/all/richmenu/{rid}", headers=BOT).status_code, 400)
        self.assertEqual(self.upload(rid, b"not an image").status_code, 400)
        self.assertEqual(self.upload(rid, PNG, "text/plain").status_code, 415)
        self.assertEqual(self.upload(rid).status_code, 200)
        self.assertEqual(self.upload(rid).status_code, 400)  # 不能重複上傳
        self.assertEqual(self.client.get(f"/v2/bot/richmenu/{rid}/content", headers=BOT).data, PNG)

        self.assertIsNone(self.current("u1"))
        self.emitted.clear()
        self.assertEqual(self.client.post(f"/v2/bot/user/all/richmenu/{rid}", headers=BOT).status_code, 200)
        self.assertEqual(sorted(r for _, r in self.emitted), ["u1", "u2"])
        self.assertEqual(self.client.get("/v2/bot/user/all/richmenu", headers=BOT).get_json(), {"richMenuId": rid})

        menu = self.current("u1")
        self.assertEqual(menu["richMenuId"], rid)
        self.assertEqual(menu["chatBarText"], "選單")
        self.assertTrue(menu["imageUrl"].endswith(f"/richmenu/{rid}/image"))
        self.assertNotIn("imageExt", menu)
        self.assertEqual(self.client.get(f"/richmenu/{rid}/image").data, PNG)
        self.assertEqual(self.client.get("/richmenu/current?userId=u1&botId=default").status_code, 401)

        lst = self.client.get("/v2/bot/richmenu/list", headers=BOT).get_json()["richmenus"]
        self.assertEqual([m["richMenuId"] for m in lst], [rid])

        self.client.delete("/v2/bot/user/all/richmenu", headers=BOT)
        self.assertIsNone(self.current("u1"))

    def test_per_user_link_overrides_default(self):
        default, special = self.create(), self.create(menu_body("vip"))
        self.upload(default)
        self.upload(special)
        self.client.post(f"/v2/bot/user/all/richmenu/{default}", headers=BOT)
        self.emitted.clear()
        self.assertEqual(self.client.post(f"/v2/bot/user/u1/richmenu/{special}", headers=BOT).status_code, 200)
        self.assertEqual(self.emitted, [("richmenu_changed", "u1")])
        self.assertEqual(self.current("u1")["name"], "vip")
        self.assertEqual(self.current("u2")["name"], "main")
        self.assertEqual(self.client.get("/v2/bot/user/u1/richmenu", headers=BOT).get_json(), {"richMenuId": special})
        self.assertEqual(self.client.get("/v2/bot/user/u2/richmenu", headers=BOT).status_code, 404)

        self.client.delete("/v2/bot/user/u1/richmenu", headers=BOT)
        self.assertEqual(self.current("u1")["name"], "main")

        res = self.client.post("/v2/bot/richmenu/bulk/link", headers=BOT,
                               json={"richMenuId": special, "userIds": ["u1", "u2"]})
        self.assertEqual(res.status_code, 202)
        self.assertEqual(self.current("u2")["name"], "vip")
        self.client.post("/v2/bot/richmenu/bulk/unlink", headers=BOT, json={"userIds": ["u1", "u2"]})
        self.assertEqual(self.current("u2")["name"], "main")

        # 刪除預設選單後，所有人都看不到
        self.client.delete(f"/v2/bot/richmenu/{default}", headers=BOT)
        self.assertIsNone(self.current("u1"))
        self.assertEqual(self.client.get(f"/v2/bot/richmenu/{default}", headers=BOT).status_code, 404)

    def test_menus_are_isolated_between_bots(self):
        _, other = make_bot("shop")
        make_user("u3", bots=("default", "shop"))
        rid = self.create()
        self.upload(rid)
        self.client.post(f"/v2/bot/user/all/richmenu/{rid}", headers=BOT)
        # 另一個 Bot 看不到、也不能操作預設 Bot 的選單
        self.assertEqual(self.client.get("/v2/bot/richmenu/list", headers=other).get_json()["richmenus"], [])
        self.assertEqual(self.client.get(f"/v2/bot/richmenu/{rid}", headers=other).status_code, 404)
        self.assertEqual(self.client.delete(f"/v2/bot/richmenu/{rid}", headers=other).status_code, 404)
        self.assertEqual(self.client.get("/v2/bot/user/all/richmenu", headers=other).status_code, 404)
        # 使用者在兩個 Bot 各自看到各自的選單
        shop_menu = self.client.post("/v2/bot/richmenu", headers=other, json=menu_body("shop")).get_json()["richMenuId"]
        self.client.post(f"/v2/bot/richmenu/{shop_menu}/content", headers={**other, "Content-Type": "image/png"}, data=PNG)
        self.client.post(f"/v2/bot/user/all/richmenu/{shop_menu}", headers=other)
        h = app_headers("u3")
        cur = lambda b: self.client.get(f"/richmenu/current?userId=u3&botId={b}", headers=h).get_json()["richMenu"]
        self.assertEqual(cur("default")["name"], "main")
        self.assertEqual(cur("shop")["name"], "shop")
        # 不是好友的 Bot 查不到
        self.assertEqual(self.client.get("/richmenu/current?userId=u1&botId=shop", headers=app_headers("u1")).status_code, 404)

    def test_blocked_user_has_no_menu(self):
        rid = self.create()
        self.upload(rid)
        self.client.post(f"/v2/bot/user/all/richmenu/{rid}", headers=BOT)
        platform_app.db.set_blocked("default", "u1", True)
        self.assertIsNone(self.current("u1"))

    def test_alias_and_switch(self):
        a = self.create(menu_body("A"))
        b = self.create(menu_body("B"))
        self.upload(a)
        self.upload(b)
        self.assertEqual(self.client.post("/v2/bot/richmenu/alias", headers=BOT,
                                          json={"richMenuAliasId": "page-b", "richMenuId": b}).status_code, 200)
        self.assertEqual(self.client.post("/v2/bot/richmenu/alias", headers=BOT,
                                          json={"richMenuAliasId": "page-b", "richMenuId": a}).status_code, 400)
        self.assertEqual(self.client.get("/v2/bot/richmenu/alias/page-b", headers=BOT).get_json()["richMenuId"], b)
        self.assertEqual(len(self.client.get("/v2/bot/richmenu/alias/list", headers=BOT).get_json()["aliases"]), 1)

        self.client.post(f"/v2/bot/user/all/richmenu/{a}", headers=BOT)
        res = self.client.post("/richmenu/switch", headers=app_headers("u1"),
                               json={"userId": "u1", "botId": "default", "richMenuAliasId": "page-b"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "SUCCESS")
        self.assertEqual(self.current("u1")["name"], "B")
        res = self.client.post("/richmenu/switch", headers=app_headers("u1"),
                               json={"userId": "u1", "botId": "default", "richMenuAliasId": "nope"})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["status"], "RICHMENU_ALIAS_ID_NOTFOUND")

        self.client.post("/v2/bot/richmenu/alias/page-b", headers=BOT, json={"richMenuId": a})
        self.assertEqual(self.client.get("/v2/bot/richmenu/alias/page-b", headers=BOT).get_json()["richMenuId"], a)
        self.assertEqual(self.client.delete("/v2/bot/richmenu/alias/page-b", headers=BOT).status_code, 200)
        self.assertEqual(self.client.delete("/v2/bot/richmenu/alias/page-b", headers=BOT).status_code, 404)


class TestRichMenuSdk(RichMenuBase):
    def test_v1_sdk(self):
        from localbot import LineBotApi
        from localbot.models import (MessageAction, RichMenu, RichMenuAlias, RichMenuArea,
                                     RichMenuBounds, RichMenuSize, RichMenuSwitchAction)
        api = LineBotApi(CHANNEL_ACCESS_TOKEN, server_url="http://localbot.test")
        fake = route_to(self.client)
        with mock.patch("requests.request", side_effect=fake), \
                mock.patch("requests.post", side_effect=lambda url, **kw: fake("POST", url, **kw)), \
                mock.patch("requests.get", side_effect=lambda url, **kw: fake("GET", url, **kw)):
            menu = RichMenu(
                size=RichMenuSize(width=2500, height=843), selected=False, name="v1", chat_bar_text="點我",
                areas=[
                    RichMenuArea(bounds=RichMenuBounds(x=0, y=0, width=1250, height=843),
                                 action=MessageAction(label="a", text="a")),
                    RichMenuArea(bounds=RichMenuBounds(x=1250, y=0, width=1250, height=843),
                                 action=RichMenuSwitchAction(rich_menu_alias_id="next", data="go")),
                ],
            )
            rid = api.create_rich_menu(menu)
            api.set_rich_menu_image(rid, "image/png", PNG)
            self.assertEqual(api.get_rich_menu_image(rid).content, PNG)
            got = api.get_rich_menu(rid)
            self.assertEqual((got.rich_menu_id, got.chat_bar_text), (rid, "點我"))
            self.assertEqual(len(api.get_rich_menu_list()), 1)
            api.set_default_rich_menu(rid)
            self.assertEqual(api.get_default_rich_menu_id(), rid)
            api.link_rich_menu_to_user("u1", rid)
            self.assertEqual(api.get_rich_menu_id_of_user("u1"), rid)
            api.create_rich_menu_alias(RichMenuAlias(rich_menu_alias_id="next", rich_menu_id=rid))
            self.assertEqual(api.get_rich_menu_alias("next").rich_menu_id, rid)
            self.assertEqual(len(api.get_rich_menu_alias_list()), 1)
            api.unlink_rich_menu_from_user("u1")
            api.cancel_default_rich_menu()
            api.delete_rich_menu_alias("next")
            api.delete_rich_menu(rid)
            self.assertEqual(api.get_rich_menu_list(), [])

    def test_v3_sdk(self):
        from localbot.v3.messaging import (
            ApiClient, Configuration, CreateRichMenuAliasRequest, MessageAction, MessagingApi,
            MessagingApiBlob, RichMenuArea, RichMenuBounds, RichMenuBulkLinkRequest, RichMenuRequest,
            RichMenuSize, URIAction,
        )
        client = ApiClient(Configuration(access_token=CHANNEL_ACCESS_TOKEN, host="http://localbot.test"))
        client._session.request = route_to(self.client)
        api, blob = MessagingApi(client), MessagingApiBlob(client)

        req = RichMenuRequest(
            size=RichMenuSize(width=2500, height=843), selected=True, name="v3", chat_bar_text="選單",
            areas=[
                RichMenuArea(bounds=RichMenuBounds(x=0, y=0, width=1250, height=843),
                             action=MessageAction(label="a", text="a")),
                RichMenuArea(bounds=RichMenuBounds(x=1250, y=0, width=1250, height=843),
                             action=URIAction(label="b", uri="https://example.com")),
            ],
        )
        api.validate_rich_menu_object(req)
        rid = api.create_rich_menu(req).rich_menu_id
        blob.set_rich_menu_image(rid, body=bytearray(PNG), _headers={"Content-Type": "image/png"})
        self.assertEqual(blob.get_rich_menu_image(rid), bytearray(PNG))
        menu = api.get_rich_menu(rid)
        self.assertEqual((menu.size.width, menu.chat_bar_text), (2500, "選單"))
        self.assertEqual(menu.areas[1].action.uri, "https://example.com")
        self.assertEqual(api.get_rich_menu_list().richmenus[0].rich_menu_id, rid)
        api.set_default_rich_menu(rid)
        self.assertEqual(api.get_default_rich_menu_id().rich_menu_id, rid)
        api.link_rich_menu_id_to_users(RichMenuBulkLinkRequest(rich_menu_id=rid, user_ids=["u1", "u2"]))
        self.assertEqual(api.get_rich_menu_id_of_user("u2").rich_menu_id, rid)
        api.create_rich_menu_alias(CreateRichMenuAliasRequest(rich_menu_alias_id="home", rich_menu_id=rid))
        self.assertEqual(api.get_rich_menu_alias_list().aliases[0].rich_menu_alias_id, "home")
        api.delete_rich_menu(rid)
        self.assertEqual(api.get_rich_menu_list().richmenus, [])


if __name__ == "__main__":
    unittest.main()
