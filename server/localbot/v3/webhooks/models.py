"""
對應 linebot.v3.webhooks 的事件模型（屬性一律 snake_case）。

    @handler.add(MessageEvent, message=TextMessageContent)
    def on_text(event):
        event.reply_token, event.source.user_id, event.message.text
"""
from typing import Any, Dict, Optional

from .._base import Model, to_snake


# ============================================================================
# Sources
# ============================================================================
class Source(Model):
    pass


class UserSource(Source):
    _type = "user"


class GroupSource(Source):
    _type = "group"


class RoomSource(Source):
    _type = "room"


# ============================================================================
# Message contents
# ============================================================================
class MessageContent(Model):
    pass


class TextMessageContent(MessageContent):
    _type = "text"


class ImageMessageContent(MessageContent):
    _type = "image"


class VideoMessageContent(MessageContent):
    _type = "video"


class AudioMessageContent(MessageContent):
    _type = "audio"


class FileMessageContent(MessageContent):
    _type = "file"


class LocationMessageContent(MessageContent):
    _type = "location"


class StickerMessageContent(MessageContent):
    _type = "sticker"


class ContentProvider(Model):
    pass


class DeliveryContext(Model):
    pass


class PostbackContent(Model):
    pass


class FollowDetail(Model):
    pass


# ============================================================================
# Events
# ============================================================================
class Event(Model):
    pass


class MessageEvent(Event):
    _type = "message"


class PostbackEvent(Event):
    _type = "postback"


class FollowEvent(Event):
    _type = "follow"


class UnfollowEvent(Event):
    _type = "unfollow"


class JoinEvent(Event):
    _type = "join"


class LeaveEvent(Event):
    _type = "leave"


class MemberJoinedEvent(Event):
    _type = "memberJoined"


class MemberLeftEvent(Event):
    _type = "memberLeft"


class BeaconEvent(Event):
    _type = "beacon"


class AccountLinkEvent(Event):
    _type = "accountLink"


class UnknownEvent(Event):
    pass


class CallbackRequest(Model):
    pass


_SOURCES = {"user": UserSource, "group": GroupSource, "room": RoomSource}
_CONTENTS = {c._type: c for c in (
    TextMessageContent, ImageMessageContent, VideoMessageContent, AudioMessageContent,
    FileMessageContent, LocationMessageContent, StickerMessageContent,
)}
_EVENTS = {c._type: c for c in (
    MessageEvent, PostbackEvent, FollowEvent, UnfollowEvent, JoinEvent, LeaveEvent,
    MemberJoinedEvent, MemberLeftEvent, BeaconEvent, AccountLinkEvent,
)}


def _snake_obj(cls, data: Dict[str, Any]):
    """把 dict 轉成指定類別的物件，巢狀 dict 也轉成可用屬性存取的 Model。"""
    obj = cls.from_dict(data)
    for key, value in data.items():
        if isinstance(value, dict):
            object.__setattr__(obj, to_snake(key), _snake_obj(Model, value))
    return obj


def _ensure_attrs(obj, *names):
    for n in names:
        if not hasattr(obj, n):
            object.__setattr__(obj, n, None)
    return obj


def parse_event(data: Dict[str, Any]) -> Optional[Event]:
    event_type = data.get("type")
    event_cls = _EVENTS.get(event_type, UnknownEvent)
    event = _snake_obj(event_cls, data)

    src = data.get("source") or {}
    source = _snake_obj(_SOURCES.get(src.get("type"), Source), src)
    event.source = _ensure_attrs(source, "user_id", "group_id", "room_id")

    event.delivery_context = _snake_obj(DeliveryContext, data.get("deliveryContext") or {"isRedelivery": False})
    _ensure_attrs(event.delivery_context, "is_redelivery")
    _ensure_attrs(event, "reply_token", "webhook_event_id", "timestamp", "mode")

    if event_cls is MessageEvent:
        msg = data.get("message") or {}
        content_cls = _CONTENTS.get(msg.get("type"), MessageContent)
        message = _snake_obj(content_cls, msg)
        if isinstance(msg.get("contentProvider"), dict):
            message.content_provider = _snake_obj(ContentProvider, msg["contentProvider"])
        event.message = _ensure_attrs(message, "id", "quote_token", "quoted_message_id")
    elif event_cls is PostbackEvent:
        pb = data.get("postback") or {}
        postback = _snake_obj(PostbackContent, pb)
        object.__setattr__(postback, "params", pb.get("params"))  # 官方為 Dict[str, str]
        event.postback = _ensure_attrs(postback, "data")
    elif event_cls is FollowEvent:
        event.follow = _snake_obj(FollowDetail, data.get("follow") or {"isUnblocked": False})
    return event


__all__ = [name for name, obj in list(globals().items())
           if isinstance(obj, type) and issubclass(obj, Model)] + ["parse_event"]
