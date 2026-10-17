"""
對應 linebot.v3 的 WebhookHandler / WebhookParser。

與 v1 的差異：
- 事件改用 localbot.v3.webhooks 的模型（TextMessageContent 等）。
- 處理函式若有 2 個參數，第二個參數為 destination（與官方 v3 相同）。
"""
import json
from typing import List, Optional

from ..exceptions import InvalidSignatureError
from ..utils import check_signature
from ..webhook import WebhookHandler as _V1WebhookHandler
from .webhooks.models import MessageEvent, parse_event


class WebhookHandler(_V1WebhookHandler):
    _message_event_cls = MessageEvent

    @staticmethod
    def _parse_event(raw_event):
        return parse_event(raw_event)

    def _call_handler(self, func, event, destination: Optional[str] = None):
        import inspect
        try:
            param_count = len(inspect.signature(func).parameters)
        except (TypeError, ValueError):
            param_count = 1
        if param_count >= 2:
            func(event, destination)
        else:
            func(event)


class WebhookPayload:
    def __init__(self, events: List, destination: Optional[str] = None):
        self.events = events
        self.destination = destination


class WebhookParser:
    def __init__(self, channel_secret: str, skip_signature_verification=lambda: False):
        self.channel_secret = channel_secret
        self.skip_signature_verification = skip_signature_verification

    def parse(self, body: str, signature: str, as_payload: bool = False):
        if not self.skip_signature_verification():
            if not signature or not check_signature(self.channel_secret, body, signature):
                raise InvalidSignatureError("Invalid signature. signature=" + str(signature))
        payload = json.loads(body)
        events = [parse_event(e) for e in payload.get("events", []) if isinstance(e, dict)]
        if as_payload:
            return WebhookPayload(events, payload.get("destination"))
        return events
