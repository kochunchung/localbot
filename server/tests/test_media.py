"""
測試：影片 / 檔案上傳、文件下載方式、Imagemap 圖片路由與 SDK 模型。
"""
import io
import os
import unittest

from helpers import app_headers, fresh_db, make_user, platform_app
from localbot.models import (
    BaseSize, ImagemapArea, ImagemapSendMessage, MessageImagemapAction, URIImagemapAction,
    parse_event,
)

USER_ID = "media_user"


class TestMedia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_db("media")
        cls.headers = make_user(USER_ID)
        platform_app.app.config["TESTING"] = True
        cls.client = platform_app.app.test_client()
        os.makedirs(platform_app.MEDIA_DIR, exist_ok=True)
        os.makedirs(platform_app.IMAGEMAP_DIR, exist_ok=True)

    def _upload(self, name, data=b"data", msg_id="m1"):
        return self.client.post(
            "/upload",
            headers=self.headers,
            data={"userId": USER_ID, "messageId": msg_id, "file": (io.BytesIO(data), name)},
            content_type="multipart/form-data",
        )

    def test_upload_video_and_documents(self):
        self.assertEqual(self._upload("clip.mp4", msg_id="v1").status_code, 200)
        res = self._upload("report.pdf", msg_id="f1")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["url"].endswith("/media/f1.pdf"))
        self.assertEqual(self._upload("evil.exe", msg_id="x1").status_code, 400)
        self.assertEqual(self._upload("page.html", msg_id="x2").status_code, 400)

    def test_documents_are_downloaded_not_inline(self):
        self._upload("sheet.xlsx", msg_id="f2")
        res = self.client.get("/media/f2.xlsx")
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))
        self._upload("clip.mp4", msg_id="v2")
        res = self.client.get("/media/v2.mp4")
        self.assertNotIn("attachment", res.headers.get("Content-Disposition", ""))

    def test_video_supports_range_requests(self):
        self._upload("clip.mp4", data=b"0123456789", msg_id="v3")
        res = self.client.get("/media/v3.mp4", headers={"Range": "bytes=2-5"})
        self.assertEqual(res.status_code, 206)
        self.assertEqual(res.data, b"2345")

    def test_imagemap_demo_and_custom(self):
        res = self.client.get("/imagemap/demo/1040")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data.startswith(b"\x89PNG"))
        self.assertEqual(self.client.get("/imagemap/demo/123").status_code, 404)
        self.assertEqual(self.client.get("/imagemap/missing/240").status_code, 404)

        folder = os.path.join(platform_app.IMAGEMAP_DIR, "menu1")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "banner.png"), "wb") as f:
            f.write(b"\x89PNGfake")
        # 只放一張圖，所有寬度都回傳同一張
        for size in (240, 700, 1040):
            res = self.client.get(f"/imagemap/menu1/{size}")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.data, b"\x89PNGfake")

    def test_imagemap_model_and_validation(self):
        msg = ImagemapSendMessage(
            base_url="https://x/imagemap/demo", alt_text="map",
            base_size=BaseSize(width=1040, height=520),
            actions=[
                URIImagemapAction(link_uri="https://example.com", area=ImagemapArea(x=0, y=0, width=520, height=520)),
                MessageImagemapAction(text="hi", area=ImagemapArea(x=520, y=0, width=520, height=520)),
            ],
        ).as_json_dict()
        self.assertEqual(msg["type"], "imagemap")
        self.assertEqual(msg["baseSize"], {"height": 520, "width": 1040})
        self.assertEqual(msg["actions"][0]["linkUri"], "https://example.com")
        self.assertIsNone(platform_app.validate_messages([msg]))

    def test_v1_snake_case_aliases(self):
        ev = parse_event({"type": "message", "replyToken": "r", "source": {"type": "user", "userId": "u"},
                          "message": {"type": "file", "id": "1", "fileName": "a.pdf", "fileSize": 10}})
        self.assertEqual((ev.message.file_name, ev.message.file_size), ("a.pdf", 10))
        ev = parse_event({"type": "message", "source": {"type": "user", "userId": "u"},
                          "message": {"type": "sticker", "id": "2", "packageId": "1", "stickerId": "3"}})
        self.assertEqual((ev.message.package_id, ev.message.sticker_id), ("1", "3"))


if __name__ == "__main__":
    unittest.main()
