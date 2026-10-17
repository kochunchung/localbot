"""
WebhookHandler implementation for localbot SDK.
"""
from typing import Callable, Dict, List, Optional, Tuple, Type, Union
import json
import inspect
from .exceptions import InvalidSignatureError
from .utils import check_signature
from .models import Event, MessageEvent, parse_event


class WebhookHandler:
    # 子類別（例如 localbot.v3）可替換事件解析器與 MessageEvent 類別
    _message_event_cls: Type = MessageEvent

    @staticmethod
    def _parse_event(raw_event):
        return parse_event(raw_event)

    def __init__(self, channel_secret: str):
        self.channel_secret = channel_secret
        self._handlers: Dict[Tuple[Type, Optional[Type]], List[Callable]] = {}
        self._default_handler: Optional[Callable] = None

    def add(self, event: Type[Event], message: Optional[Type] = None):
        """Decorator to add an event handler, matching linebot.WebhookHandler.add."""
        def decorator(func: Callable):
            key = (event, message)
            if key not in self._handlers:
                self._handlers[key] = []
            self._handlers[key].append(func)
            return func
        return decorator

    def default(self):
        """Decorator to set a default fallback handler."""
        def decorator(func: Callable):
            self._default_handler = func
            return func
        return decorator

    def handle(self, body: str, signature: Optional[str] = None):
        """Handle incoming webhook payload string and verify signature."""
        # 與官方 LINE SDK 相同：有設定 channel_secret 時，一律要求簽名
        # （缺少簽名標頭也視為驗證失敗，避免被偽造 Webhook）
        if self.channel_secret:
            if not signature or not check_signature(self.channel_secret, body, signature):
                raise InvalidSignatureError("Signature verification failed.")

        try:
            payload = json.loads(body) if isinstance(body, str) else body
        except Exception as e:
            raise ValueError(f"Failed to parse JSON body: {e}")

        if not isinstance(payload, dict):
            return
        events_data = payload.get("events", [])
        destination = payload.get("destination")

        for raw_event in events_data if isinstance(events_data, list) else []:
            if not isinstance(raw_event, dict):
                continue
            event_obj = self._parse_event(raw_event)
            if event_obj is None:
                continue
            self._dispatch(event_obj, destination)

    def _dispatch(self, event, destination: Optional[str] = None):
        """Dispatch event to registered callback."""
        dispatched = False
        msg_event_cls = self._message_event_cls

        message = getattr(event, "message", None)
        if isinstance(event, msg_event_cls) and message is not None:
            # 1. Exact match for (MessageEvent, MessageSubclass)
            key = (msg_event_cls, message.__class__)
            if key in self._handlers:
                for func in self._handlers[key]:
                    self._call_handler(func, event, destination)
                dispatched = True

        # 2. Match for (EventSubclass, None)
        event_cls = event.__class__
        if (event_cls, None) in self._handlers:
            for func in self._handlers[(event_cls, None)]:
                self._call_handler(func, event, destination)
            dispatched = True

        # 3. Fallback to default handler
        if not dispatched and self._default_handler:
            self._call_handler(self._default_handler, event, destination)

    def _call_handler(self, func: Callable, event, destination: Optional[str] = None):
        sig = inspect.signature(func)
        param_count = len(sig.parameters)
        if param_count == 1:
            func(event)
        elif param_count == 2 and isinstance(event, MessageEvent):
            func(event, event.message)
        else:
            func(event)
