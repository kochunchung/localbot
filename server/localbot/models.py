"""
Models for localbot SDK, matching linebot.models interfaces.
"""
from typing import Any, Dict, List, Optional, Union
import json
import time


# ============================================================================
# Base JSON Model
# ============================================================================
class BaseJsonModel:
    def as_json_dict(self) -> Dict[str, Any]:
        result = {}
        for key, value in self.__dict__.items():
            if value is None or key.startswith('_'):
                continue
            # Convert snake_case to camelCase if needed, or preserve
            if hasattr(value, 'as_json_dict'):
                result[key] = value.as_json_dict()
            elif isinstance(value, list):
                result[key] = [
                    item.as_json_dict() if hasattr(item, 'as_json_dict') else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def to_dict(self) -> Dict[str, Any]:
        return self.as_json_dict()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.as_json_dict()})"


# ============================================================================
# Actions
# ============================================================================
class Action(BaseJsonModel):
    def __init__(self, type: str, label: Optional[str] = None):
        self.type = type
        self.label = label


class PostbackAction(Action):
    def __init__(self, label: Optional[str] = None, data: str = "", display_text: Optional[str] = None, text: Optional[str] = None):
        super().__init__(type="postback", label=label)
        self.data = data
        self.displayText = display_text or text


class MessageAction(Action):
    def __init__(self, label: Optional[str] = None, text: str = ""):
        super().__init__(type="message", label=label)
        self.text = text


class URIAction(Action):
    def __init__(self, label: Optional[str] = None, uri: str = ""):
        super().__init__(type="uri", label=label)
        self.uri = uri


class DatetimePickerAction(Action):
    def __init__(self, label: Optional[str] = None, data: str = "", mode: str = "datetime",
                 initial: Optional[str] = None, max: Optional[str] = None, min: Optional[str] = None):
        super().__init__(type="datetimepicker", label=label)
        self.data = data
        self.mode = mode
        self.initial = initial
        self.max = max
        self.min = min


class CameraAction(Action):
    def __init__(self, label: Optional[str] = None):
        super().__init__(type="camera", label=label)


class CameraRollAction(Action):
    def __init__(self, label: Optional[str] = None):
        super().__init__(type="cameraRoll", label=label)


class LocationAction(Action):
    def __init__(self, label: Optional[str] = None):
        super().__init__(type="location", label=label)


# ============================================================================
# Backward Compatibility Aliases (舊版 LINE SDK 命名別名相容)
# ============================================================================
PostbackTemplateAction = PostbackAction
MessageTemplateAction = MessageAction
URITemplateAction = URIAction
DatetimePickerTemplateAction = DatetimePickerAction
CameraTemplateAction = CameraAction
CameraRollTemplateAction = CameraRollAction
LocationTemplateAction = LocationAction


class QuickReplyButton(BaseJsonModel):
    def __init__(self, action: Optional[Action] = None, image_url: Optional[str] = None):
        self.type = "action"
        self.action = action
        self.imageUrl = image_url


class QuickReply(BaseJsonModel):
    def __init__(self, items: Optional[List[QuickReplyButton]] = None):
        self.items = items or []



# ============================================================================
# Templates
# ============================================================================
class Template(BaseJsonModel):
    def __init__(self, type: str):
        self.type = type


class ButtonsTemplate(Template):
    def __init__(
        self,
        text: str = "",
        title: Optional[str] = None,
        actions: Optional[List[Action]] = None,
        thumbnail_image_url: Optional[str] = None,
        image_aspect_ratio: Optional[str] = None,
        image_size: Optional[str] = None,
        image_background_color: Optional[str] = None,
        default_action: Optional[Action] = None,
    ):
        super().__init__(type="buttons")
        self.text = text
        self.title = title
        self.actions = actions or []
        self.thumbnailImageUrl = thumbnail_image_url
        self.imageAspectRatio = image_aspect_ratio
        self.imageSize = image_size
        self.imageBackgroundColor = image_background_color
        self.defaultAction = default_action


class ConfirmTemplate(Template):
    def __init__(self, text: str = "", actions: Optional[List[Action]] = None):
        super().__init__(type="confirm")
        self.text = text
        self.actions = actions or []


class CarouselColumn(BaseJsonModel):
    def __init__(
        self,
        text: str = "",
        title: Optional[str] = None,
        actions: Optional[List[Action]] = None,
        thumbnail_image_url: Optional[str] = None,
        image_background_color: Optional[str] = None,
        default_action: Optional[Action] = None,
    ):
        self.text = text
        self.title = title
        self.actions = actions or []
        self.thumbnailImageUrl = thumbnail_image_url
        self.imageBackgroundColor = image_background_color
        self.defaultAction = default_action


class CarouselTemplate(Template):
    def __init__(
        self,
        columns: Optional[List[CarouselColumn]] = None,
        image_aspect_ratio: Optional[str] = None,
        image_size: Optional[str] = None,
    ):
        super().__init__(type="carousel")
        self.columns = columns or []
        self.imageAspectRatio = image_aspect_ratio
        self.imageSize = image_size


class ImageCarouselColumn(BaseJsonModel):
    def __init__(self, image_url: str, action: Action):
        self.imageUrl = image_url
        self.action = action


class ImageCarouselTemplate(Template):
    def __init__(self, columns: Optional[List[ImageCarouselColumn]] = None):
        super().__init__(type="image_carousel")
        self.columns = columns or []


# ============================================================================
# Send Messages (Bot -> Client)
# ============================================================================
class SendMessage(BaseJsonModel):
    def __init__(self, type: str, quick_reply: Any = None):
        self.type = type
        self.quickReply = quick_reply


class TextSendMessage(SendMessage):
    def __init__(self, text: str, quick_reply: Any = None, quote_token: Optional[str] = None):
        super().__init__(type="text", quick_reply=quick_reply)
        self.text = text
        self.quoteToken = quote_token


class ImageSendMessage(SendMessage):
    def __init__(self, original_content_url: str, preview_image_url: Optional[str] = None, quick_reply: Any = None):
        super().__init__(type="image", quick_reply=quick_reply)
        self.originalContentUrl = original_content_url
        self.previewImageUrl = preview_image_url or original_content_url


class AudioSendMessage(SendMessage):
    def __init__(self, original_content_url: str, duration: int = 0, quick_reply: Any = None):
        super().__init__(type="audio", quick_reply=quick_reply)
        self.originalContentUrl = original_content_url
        self.duration = duration


class VideoSendMessage(SendMessage):
    def __init__(self, original_content_url: str, preview_image_url: Optional[str] = None, tracking_id: Optional[str] = None, quick_reply: Any = None):
        super().__init__(type="video", quick_reply=quick_reply)
        self.originalContentUrl = original_content_url
        self.previewImageUrl = preview_image_url or original_content_url
        self.trackingId = tracking_id


class FileSendMessage(SendMessage):
    def __init__(self, original_content_url: str, file_name: str, quick_reply: Any = None):
        super().__init__(type="file", quick_reply=quick_reply)
        self.originalContentUrl = original_content_url
        self.fileName = file_name


class StickerSendMessage(SendMessage):
    def __init__(self, package_id: Union[str, int], sticker_id: Union[str, int], quick_reply: Any = None):
        super().__init__(type="sticker", quick_reply=quick_reply)
        self.packageId = str(package_id)
        self.stickerId = str(sticker_id)



class LocationSendMessage(SendMessage):
    def __init__(self, title: str, address: str, latitude: float, longitude: float, quick_reply: Any = None):
        super().__init__(type="location", quick_reply=quick_reply)
        self.title = title
        self.address = address
        self.latitude = latitude
        self.longitude = longitude


class TemplateSendMessage(SendMessage):
    def __init__(self, alt_text: str, template: Template, quick_reply: Any = None):
        super().__init__(type="template", quick_reply=quick_reply)
        self.altText = alt_text
        self.template = template


class FlexSendMessage(SendMessage):
    def __init__(self, alt_text: str, contents: Union[Dict[str, Any], Any], quick_reply: Any = None):
        super().__init__(type="flex", quick_reply=quick_reply)
        self.altText = alt_text
        self.contents = contents.as_json_dict() if hasattr(contents, 'as_json_dict') else contents


class Sender(BaseJsonModel):
    def __init__(self, name: Optional[str] = None, icon_url: Optional[str] = None):
        self.name = name
        self.iconUrl = icon_url


class Profile(BaseJsonModel):
    def __init__(
        self,
        display_name: str = "",
        user_id: str = "",
        picture_url: Optional[str] = None,
        status_message: Optional[str] = None,
        language: Optional[str] = None,
    ):
        self.display_name = display_name
        self.displayName = display_name
        self.user_id = user_id
        self.userId = user_id
        self.picture_url = picture_url
        self.pictureUrl = picture_url
        self.status_message = status_message
        self.statusMessage = status_message
        self.language = language



# ============================================================================
# Flex Message Containers & Components (for SDK compatibility)
# ============================================================================
class FlexContainer(BaseJsonModel):
    def __init__(self, type: str, **kwargs):
        self.type = type
        for k, v in kwargs.items():
            setattr(self, k, v)


class BubbleContainer(FlexContainer):
    def __init__(self, header: Any = None, hero: Any = None, body: Any = None,
                 footer: Any = None, styles: Any = None, direction: Optional[str] = None, **kwargs):
        super().__init__(type="bubble", **kwargs)
        self.header = header
        self.hero = hero
        self.body = body
        self.footer = footer
        self.styles = styles
        self.direction = direction


class CarouselContainer(FlexContainer):
    def __init__(self, contents: Optional[List[BubbleContainer]] = None, **kwargs):
        super().__init__(type="carousel", **kwargs)
        self.contents = contents or []


class FlexComponent(BaseJsonModel):
    def __init__(self, type: str, **kwargs):
        self.type = type
        for k, v in kwargs.items():
            setattr(self, k, v)


class BoxComponent(FlexComponent):
    def __init__(self, layout: str = "vertical", contents: Optional[List[Any]] = None, **kwargs):
        super().__init__(type="box", **kwargs)
        self.layout = layout
        self.contents = contents or []


class TextComponent(FlexComponent):
    def __init__(self, text: str = "", **kwargs):
        super().__init__(type="text", **kwargs)
        self.text = text


class ImageComponent(FlexComponent):
    def __init__(self, url: str = "", **kwargs):
        super().__init__(type="image", **kwargs)
        self.url = url


class ButtonComponent(FlexComponent):
    def __init__(self, action: Optional[Action] = None, **kwargs):
        super().__init__(type="button", **kwargs)
        self.action = action


class IconComponent(FlexComponent):
    def __init__(self, url: str = "", **kwargs):
        super().__init__(type="icon", **kwargs)
        self.url = url


class SeparatorComponent(FlexComponent):
    def __init__(self, **kwargs):
        super().__init__(type="separator", **kwargs)


class SpacerComponent(FlexComponent):
    def __init__(self, size: Optional[str] = None, **kwargs):
        super().__init__(type="spacer", **kwargs)
        self.size = size


class FillerComponent(FlexComponent):
    def __init__(self, **kwargs):
        super().__init__(type="filler", **kwargs)



# ============================================================================
# Sources
# ============================================================================
class Source(BaseJsonModel):
    def __init__(self, type: str = "user", user_id: Optional[str] = None):
        self.type = type
        self.userId = user_id

    @property
    def sender_id(self) -> Optional[str]:
        return self.userId

    @property
    def user_id(self) -> Optional[str]:
        return self.userId


class SourceUser(Source):
    def __init__(self, user_id: Optional[str] = None):
        super().__init__(type="user", user_id=user_id)


class SourceGroup(Source):
    def __init__(self, group_id: Optional[str] = None, user_id: Optional[str] = None):
        super().__init__(type="group", user_id=user_id)
        self.groupId = group_id
        self.group_id = group_id


class SourceRoom(Source):
    def __init__(self, room_id: Optional[str] = None, user_id: Optional[str] = None):
        super().__init__(type="room", user_id=user_id)
        self.roomId = room_id
        self.room_id = room_id


# ============================================================================
# Incoming Message Contents (inside MessageEvent)
# ============================================================================
class Message(BaseJsonModel):
    def __init__(self, id: str, type: str):
        self.id = id
        self.type = type


class TextMessage(Message):
    def __init__(self, id: str, text: str = "", quote_token: Optional[str] = None):
        super().__init__(id=id, type="text")
        self.text = text
        self.quoteToken = quote_token


class ImageMessage(Message):
    def __init__(self, id: str, content_provider: Optional[Dict[str, Any]] = None):
        super().__init__(id=id, type="image")
        self.contentProvider = content_provider or {"type": "line"}


class AudioMessage(Message):
    def __init__(self, id: str, duration: int = 0, content_provider: Optional[Dict[str, Any]] = None):
        super().__init__(id=id, type="audio")
        self.duration = duration
        self.contentProvider = content_provider or {"type": "line"}


class VideoMessage(Message):
    def __init__(self, id: str, duration: int = 0, content_provider: Optional[Dict[str, Any]] = None):
        super().__init__(id=id, type="video")
        self.duration = duration
        self.contentProvider = content_provider or {"type": "line"}


class StickerMessage(Message):
    def __init__(self, id: str, package_id: str = "", sticker_id: str = "", sticker_resource_type: str = "STATIC"):
        super().__init__(id=id, type="sticker")
        self.packageId = str(package_id)
        self.stickerId = str(sticker_id)
        self.stickerResourceType = sticker_resource_type


class LocationMessage(Message):
    def __init__(self, id: str, title: Optional[str] = None, address: Optional[str] = None,
                 latitude: float = 0.0, longitude: float = 0.0):
        super().__init__(id=id, type="location")
        self.title = title
        self.address = address
        self.latitude = latitude
        self.longitude = longitude


class FileMessage(Message):
    def __init__(self, id: str, file_name: str = "", file_size: int = 0):
        super().__init__(id=id, type="file")
        self.fileName = file_name
        self.fileSize = file_size


# ============================================================================
# Postback Payload
# ============================================================================
class Postback(BaseJsonModel):
    def __init__(self, data: str = "", params: Optional[Dict[str, Any]] = None):
        self.data = data
        self.params = params or {}


# ============================================================================
# Webhook Events (Client -> Bot)
# ============================================================================
class Event(BaseJsonModel):
    def __init__(self, type: str, source: Optional[Source] = None, timestamp: Optional[int] = None, mode: str = "active"):
        self.type = type
        self.source = source
        self.timestamp = timestamp or int(time.time() * 1000)
        self.mode = mode


class MessageEvent(Event):
    def __init__(
        self,
        reply_token: Optional[str] = None,
        source: Optional[Source] = None,
        message: Optional[Message] = None,
        timestamp: Optional[int] = None,
        mode: str = "active",
    ):
        super().__init__(type="message", source=source, timestamp=timestamp, mode=mode)
        self.reply_token = reply_token
        self.replyToken = reply_token
        self.message = message


class PostbackEvent(Event):
    def __init__(
        self,
        reply_token: Optional[str] = None,
        source: Optional[Source] = None,
        postback: Optional[Postback] = None,
        timestamp: Optional[int] = None,
        mode: str = "active",
    ):
        super().__init__(type="postback", source=source, timestamp=timestamp, mode=mode)
        self.reply_token = reply_token
        self.replyToken = reply_token
        self.postback = postback


class FollowEvent(Event):
    def __init__(self, reply_token: Optional[str] = None, source: Optional[Source] = None, timestamp: Optional[int] = None):
        super().__init__(type="follow", source=source, timestamp=timestamp)
        self.reply_token = reply_token
        self.replyToken = reply_token


class UnfollowEvent(Event):
    def __init__(self, source: Optional[Source] = None, timestamp: Optional[int] = None):
        super().__init__(type="unfollow", source=source, timestamp=timestamp)


class JoinEvent(Event):
    def __init__(self, reply_token: Optional[str] = None, source: Optional[Source] = None, timestamp: Optional[int] = None):
        super().__init__(type="join", source=source, timestamp=timestamp)
        self.reply_token = reply_token
        self.replyToken = reply_token


class LeaveEvent(Event):
    def __init__(self, source: Optional[Source] = None, timestamp: Optional[int] = None):
        super().__init__(type="leave", source=source, timestamp=timestamp)


class MemberJoinedEvent(Event):
    def __init__(self, reply_token: Optional[str] = None, source: Optional[Source] = None,
                 joined: Optional[Dict[str, Any]] = None, timestamp: Optional[int] = None):
        super().__init__(type="memberJoined", source=source, timestamp=timestamp)
        self.reply_token = reply_token
        self.replyToken = reply_token
        self.joined = joined or {}


class MemberLeftEvent(Event):
    def __init__(self, source: Optional[Source] = None, left: Optional[Dict[str, Any]] = None, timestamp: Optional[int] = None):
        super().__init__(type="memberLeft", source=source, timestamp=timestamp)
        self.left = left or {}


class BeaconEvent(Event):
    def __init__(self, reply_token: Optional[str] = None, source: Optional[Source] = None,
                 beacon: Optional[Dict[str, Any]] = None, timestamp: Optional[int] = None):
        super().__init__(type="beacon", source=source, timestamp=timestamp)
        self.reply_token = reply_token
        self.replyToken = reply_token
        self.beacon = beacon or {}


class AccountLinkEvent(Event):
    def __init__(self, reply_token: Optional[str] = None, source: Optional[Source] = None,
                 link: Optional[Dict[str, Any]] = None, timestamp: Optional[int] = None):
        super().__init__(type="accountLink", source=source, timestamp=timestamp)
        self.reply_token = reply_token
        self.replyToken = reply_token
        self.link = link or {}


# ============================================================================
# Event Parser Factory
# ============================================================================
def parse_event(data: Dict[str, Any]) -> Optional[Event]:
    event_type = data.get("type")
    reply_token = data.get("replyToken") or data.get("reply_token")
    timestamp = data.get("timestamp")
    mode = data.get("mode", "active")

    source_data = data.get("source", {})
    user_id = source_data.get("userId") or source_data.get("user_id")
    group_id = source_data.get("groupId") or source_data.get("group_id")
    room_id = source_data.get("roomId") or source_data.get("room_id")
    source_type = source_data.get("type", "user")

    if source_type == "group" or group_id:
        source = SourceGroup(group_id=group_id, user_id=user_id)
    elif source_type == "room" or room_id:
        source = SourceRoom(room_id=room_id, user_id=user_id)
    elif user_id:
        source = SourceUser(user_id=user_id)
    else:
        source = Source(type=source_type)

    if event_type == "message":
        msg_data = data.get("message", {})
        msg_type = msg_data.get("type")
        msg_id = str(msg_data.get("id", ""))

        message_obj: Optional[Message] = None
        if msg_type == "text":
            message_obj = TextMessage(id=msg_id, text=msg_data.get("text", ""))
        elif msg_type == "image":
            message_obj = ImageMessage(id=msg_id, content_provider=msg_data.get("contentProvider"))
        elif msg_type == "audio":
            message_obj = AudioMessage(id=msg_id, duration=msg_data.get("duration", 0), content_provider=msg_data.get("contentProvider"))
        elif msg_type == "video":
            message_obj = VideoMessage(id=msg_id, duration=msg_data.get("duration", 0), content_provider=msg_data.get("contentProvider"))
        elif msg_type == "sticker":
            message_obj = StickerMessage(id=msg_id, package_id=msg_data.get("packageId", ""), sticker_id=msg_data.get("stickerId", ""))
        elif msg_type == "location":
            message_obj = LocationMessage(
                id=msg_id,
                title=msg_data.get("title"),
                address=msg_data.get("address"),
                latitude=float(msg_data.get("latitude", 0)),
                longitude=float(msg_data.get("longitude", 0))
            )
        elif msg_type == "file":
            message_obj = FileMessage(id=msg_id, file_name=msg_data.get("fileName", ""), file_size=int(msg_data.get("fileSize", 0)))
        else:
            message_obj = Message(id=msg_id, type=msg_type)

        return MessageEvent(reply_token=reply_token, source=source, message=message_obj, timestamp=timestamp, mode=mode)

    elif event_type == "postback":
        pb_data = data.get("postback", {})
        postback_obj = Postback(data=pb_data.get("data", ""), params=pb_data.get("params"))
        return PostbackEvent(reply_token=reply_token, source=source, postback=postback_obj, timestamp=timestamp, mode=mode)

    elif event_type == "follow":
        return FollowEvent(reply_token=reply_token, source=source, timestamp=timestamp)

    elif event_type == "unfollow":
        return UnfollowEvent(source=source, timestamp=timestamp)

    elif event_type == "join":
        return JoinEvent(reply_token=reply_token, source=source, timestamp=timestamp)

    elif event_type == "leave":
        return LeaveEvent(source=source, timestamp=timestamp)

    elif event_type == "memberJoined":
        return MemberJoinedEvent(reply_token=reply_token, source=source, joined=data.get("joined"), timestamp=timestamp)

    elif event_type == "memberLeft":
        return MemberLeftEvent(source=source, left=data.get("left"), timestamp=timestamp)

    elif event_type == "beacon":
        return BeaconEvent(reply_token=reply_token, source=source, beacon=data.get("beacon"), timestamp=timestamp)

    elif event_type == "accountLink":
        return AccountLinkEvent(reply_token=reply_token, source=source, link=data.get("link"), timestamp=timestamp)

    return None

