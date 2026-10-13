"""
Unit tests for localbot SDK.
"""
import pytest
import json
from localbot import LineBotApi, WebhookHandler
from localbot.exceptions import InvalidSignatureError
from localbot.utils import calculate_signature, check_signature
from localbot.models import (
    parse_event,
    MessageEvent, PostbackEvent,
    TextMessage, ImageMessage, AudioMessage,
    TextSendMessage, ImageSendMessage, ButtonsTemplate, TemplateSendMessage,
    PostbackAction, MessageAction, FlexSendMessage
)


def test_hmac_signature():
    secret = "my-secret-key"
    body = '{"events":[]}'
    sig = calculate_signature(secret, body)
    assert isinstance(sig, str)
    assert check_signature(secret, body, sig) is True
    assert check_signature(secret, body, "invalid_sig") is False
    assert check_signature("wrong_secret", body, sig) is False


def test_models_serialization():
    text_msg = TextSendMessage(text="Hello world")
    assert text_msg.as_json_dict() == {"type": "text", "text": "Hello world"}

    img_msg = ImageSendMessage(
        original_content_url="https://example.com/img.jpg",
        preview_image_url="https://example.com/preview.jpg"
    )
    d = img_msg.as_json_dict()
    assert d["type"] == "image"
    assert d["originalContentUrl"] == "https://example.com/img.jpg"

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
    assert td["type"] == "template"
    assert td["altText"] == "Alt"
    assert td["template"]["type"] == "buttons"
    assert len(td["template"]["actions"]) == 2


def test_parse_event():
    raw_payload = {
        "type": "message",
        "replyToken": "token_123",
        "timestamp": 1234567890,
        "source": {"type": "user", "userId": "user_456"},
        "message": {"type": "text", "id": "msg_789", "text": "test message"}
    }
    event = parse_event(raw_payload)
    assert isinstance(event, MessageEvent)
    assert event.reply_token == "token_123"
    assert event.source.user_id == "user_456"
    assert isinstance(event.message, TextMessage)
    assert event.message.text == "test message"

    raw_postback = {
        "type": "postback",
        "replyToken": "token_pb",
        "source": {"type": "user", "userId": "user_pb"},
        "postback": {"data": "action=submit&id=1"}
    }
    pb_event = parse_event(raw_postback)
    assert isinstance(pb_event, PostbackEvent)
    assert pb_event.postback.data == "action=submit&id=1"


def test_webhook_handler_dispatch():
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
    assert len(received) == 2
    assert received[0] == ("text", "hello handler")
    assert received[1] == ("postback", "clicked_yes")

    # Invalid signature raises
    with pytest.raises(InvalidSignatureError):
        handler.handle(body, "bad_sig")

    # Missing signature must also be rejected (same as official LINE SDK)
    with pytest.raises(InvalidSignatureError):
        handler.handle(body, None)


def test_line_bot_api_bridge():
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
    assert len(mock_bridge.replies) == 1
    assert mock_bridge.replies[0][0] == "reply_tok"
    assert mock_bridge.replies[0][1][0]["text"] == "Hi"

    api.push_message("user_abc", TextSendMessage(text="Pushed"))
    assert len(mock_bridge.pushes) == 1
    assert mock_bridge.pushes[0][0] == "user_abc"

    content = api.get_message_content("msg_123")
    assert content.content == b"mock binary data"
