"""
Standard library unittest suite for localbot SDK.
"""
import unittest
import json
from localbot import LineBotApi, WebhookHandler
from localbot.exceptions import InvalidSignatureError
from localbot.utils import calculate_signature, check_signature
from localbot.models import (
    parse_event,
    MessageEvent, PostbackEvent,
    TextMessage, ImageMessage, AudioMessage, LocationMessage, FileMessage,
    TextSendMessage, ImageSendMessage, LocationSendMessage, ButtonsTemplate, TemplateSendMessage,
    PostbackAction, MessageAction, FlexSendMessage
)


class TestLocalBotSDK(unittest.TestCase):

    def test_hmac_signature(self):
        secret = "my-secret-key"
        body = '{"events":[]}'
        sig = calculate_signature(secret, body)
        self.assertIsInstance(sig, str)
        self.assertTrue(check_signature(secret, body, sig))
        self.assertFalse(check_signature(secret, body, "invalid_sig"))
        self.assertFalse(check_signature("wrong_secret", body, sig))

    def test_models_serialization(self):
        text_msg = TextSendMessage(text="Hello world")
        self.assertEqual(text_msg.as_json_dict(), {"type": "text", "text": "Hello world"})

        img_msg = ImageSendMessage(
            original_content_url="https://example.com/img.jpg",
            preview_image_url="https://example.com/preview.jpg"
        )
        d = img_msg.as_json_dict()
        self.assertEqual(d["type"], "image")
        self.assertEqual(d["originalContentUrl"], "https://example.com/img.jpg")

        btn_template = ButtonsTemplate(
            title="Title",
            text="Text",
            actions=[
                PostbackAction(label="Click", data="act=1"),
                MessageAction(label="Say", text="Hi")
            ]
        )
        t_msg = TemplateSendMessage(alt_text="Alt", template=btn_template)
        td = t_msg.as_json_dict()
        self.assertEqual(td["type"], "template")
        self.assertEqual(td["altText"], "Alt")
        self.assertEqual(td["template"]["type"], "buttons")
        self.assertEqual(len(td["template"]["actions"]), 2)

    def test_parse_event(self):
        raw_payload = {
            "type": "message",
            "replyToken": "token_123",
            "timestamp": 1234567890,
            "source": {"type": "user", "userId": "user_456"},
            "message": {"type": "text", "id": "msg_789", "text": "test message"}
        }
        event = parse_event(raw_payload)
        self.assertIsInstance(event, MessageEvent)
        self.assertEqual(event.reply_token, "token_123")
        self.assertEqual(event.source.user_id, "user_456")
        self.assertIsInstance(event.message, TextMessage)
        self.assertEqual(event.message.text, "test message")

        raw_postback = {
            "type": "postback",
            "replyToken": "token_pb",
            "source": {"type": "user", "userId": "user_pb"},
            "postback": {"data": "action=submit&id=1"}
        }
        pb_event = parse_event(raw_postback)
        self.assertIsInstance(pb_event, PostbackEvent)
        self.assertEqual(pb_event.postback.data, "action=submit&id=1")

    def test_webhook_handler_dispatch(self):
        secret = "secret123"
        handler = WebhookHandler(secret)

        received = []

        @handler.add(MessageEvent, message=TextMessage)
        def on_text(event):
            received.append(("text", event.message.text))

        @handler.add(PostbackEvent)
        def on_postback(event):
            received.append(("postback", event.postback.data))

        body = json.dumps({
            "events": [
                {
                    "type": "message",
                    "replyToken": "tok1",
                    "source": {"type": "user", "userId": "u1"},
                    "message": {"type": "text", "id": "m1", "text": "hello handler"}
                },
                {
                    "type": "postback",
                    "replyToken": "tok2",
                    "source": {"type": "user", "userId": "u1"},
                    "postback": {"data": "clicked_yes"}
                }
            ]
        })

        sig = calculate_signature(secret, body)

        # Valid signature dispatch
        handler.handle(body, sig)
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0], ("text", "hello handler"))
        self.assertEqual(received[1], ("postback", "clicked_yes"))

        # Invalid signature raises
        with self.assertRaises(InvalidSignatureError):
            handler.handle(body, "bad_sig")

    def test_line_bot_api_bridge(self):
        api = LineBotApi("test-token")

        class MockBridge:
            def __init__(self):
                self.replies = []
                self.pushes = []

            def reply_message(self, reply_token, messages):
                self.replies.append((reply_token, messages))
                return True

            def push_message(self, to, messages):
                self.pushes.append((to, messages))
                return True

            def get_message_content(self, msg_id):
                return b"mock binary data"

        mock_bridge = MockBridge()
        api.set_bridge(mock_bridge)

        api.reply_message("reply_tok", TextSendMessage(text="Hi"))
        self.assertEqual(len(mock_bridge.replies), 1)
        self.assertEqual(mock_bridge.replies[0][0], "reply_tok")
        self.assertEqual(mock_bridge.replies[0][1][0]["text"], "Hi")

        api.push_message("user_abc", TextSendMessage(text="Pushed"))
        self.assertEqual(len(mock_bridge.pushes), 1)
        self.assertEqual(mock_bridge.pushes[0][0], "user_abc")

        content = api.get_message_content("msg_123")
        self.assertEqual(content.content, b"mock binary data")


    def test_location_and_file_models(self):
        loc_send = LocationSendMessage(title="My Place", address="Taipei 101", latitude=25.0339, longitude=121.5644)
        loc_d = loc_send.as_json_dict()
        self.assertEqual(loc_d["type"], "location")
        self.assertEqual(loc_d["title"], "My Place")
        self.assertEqual(loc_d["latitude"], 25.0339)

        # Parse incoming LocationMessage
        raw_loc = {
            "type": "message",
            "replyToken": "tok_loc",
            "source": {"type": "user", "userId": "u_loc"},
            "message": {
                "type": "location",
                "id": "msg_loc",
                "title": "Store",
                "address": "Xinyi Dist",
                "latitude": 25.033,
                "longitude": 121.564
            }
        }
        event = parse_event(raw_loc)
        self.assertIsInstance(event.message, LocationMessage)
        self.assertEqual(event.message.title, "Store")
        self.assertEqual(event.message.latitude, 25.033)

        # Parse incoming FileMessage
        raw_file = {
            "type": "message",
            "replyToken": "tok_file",
            "source": {"type": "user", "userId": "u_file"},
            "message": {"type": "file", "id": "msg_f", "fileName": "report.pdf", "fileSize": 1024}
        }
        f_event = parse_event(raw_file)
        self.assertIsInstance(f_event.message, FileMessage)
        self.assertEqual(f_event.message.fileName, "report.pdf")


if __name__ == "__main__":
    unittest.main()

