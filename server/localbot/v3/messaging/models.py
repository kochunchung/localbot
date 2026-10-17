"""
對應 linebot.v3.messaging 的訊息 / 動作 / 範本 / Flex 模型。

用法與官方相同，只接受關鍵字參數，例如：
    TextMessage(text="hi", quick_reply=QuickReply(items=[
        QuickReplyItem(action=MessageAction(label="是", text="是")),
    ]))
"""
from .._base import Model, deep_from_dict


# ============================================================================
# Actions
# ============================================================================
class Action(Model):
    pass


class MessageAction(Action):
    _type = "message"


class PostbackAction(Action):
    _type = "postback"


class URIAction(Action):
    _type = "uri"


class DatetimePickerAction(Action):
    _type = "datetimepicker"


class CameraAction(Action):
    _type = "camera"


class CameraRollAction(Action):
    _type = "cameraRoll"


class LocationAction(Action):
    _type = "location"


class ClipboardAction(Action):
    _type = "clipboard"


class RichMenuSwitchAction(Action):
    _type = "richmenuswitch"


# ============================================================================
# Quick Reply / Sender / Emoji
# ============================================================================
class QuickReplyItem(Model):
    _type = "action"


class QuickReply(Model):
    pass


class Sender(Model):
    pass


class Emoji(Model):
    pass


# ============================================================================
# Messages
# ============================================================================
class Message(Model):
    pass


class TextMessage(Message):
    _type = "text"


class TextMessageV2(Message):
    _type = "textV2"


class ImageMessage(Message):
    _type = "image"


class VideoMessage(Message):
    _type = "video"


class AudioMessage(Message):
    _type = "audio"


class LocationMessage(Message):
    _type = "location"


class StickerMessage(Message):
    _type = "sticker"


class TemplateMessage(Message):
    _type = "template"


class FlexMessage(Message):
    _type = "flex"


class ImagemapMessage(Message):
    _type = "imagemap"


class FileMessage(Message):
    """LocalBot 擴充：LINE 官方 Bot 無法傳送檔案訊息，LocalBot 可以。"""
    _type = "file"


# ============================================================================
# Imagemap
# ============================================================================
class ImagemapBaseSize(Model):
    pass


class ImagemapArea(Model):
    pass


class ImagemapAction(Model):
    pass


class URIImagemapAction(ImagemapAction):
    _type = "uri"


UriImagemapAction = URIImagemapAction


class MessageImagemapAction(ImagemapAction):
    _type = "message"


class ClipboardImagemapAction(ImagemapAction):
    _type = "clipboard"


class ImagemapVideo(Model):
    pass


class ImagemapExternalLink(Model):
    pass


# ============================================================================
# Templates
# ============================================================================
class Template(Model):
    pass


class ButtonsTemplate(Template):
    _type = "buttons"


class ConfirmTemplate(Template):
    _type = "confirm"


class CarouselTemplate(Template):
    _type = "carousel"


class CarouselColumn(Model):
    pass


class ImageCarouselTemplate(Template):
    _type = "image_carousel"


class ImageCarouselColumn(Model):
    pass


# ============================================================================
# Flex Message
# ============================================================================
class FlexContainer(Model):
    """可用 FlexContainer.from_json(json_str) 直接包住 Flex JSON。"""


class FlexBubble(FlexContainer):
    _type = "bubble"


class FlexCarousel(FlexContainer):
    _type = "carousel"


class FlexComponent(Model):
    pass


class FlexBox(FlexComponent):
    _type = "box"


class FlexText(FlexComponent):
    _type = "text"


class FlexSpan(FlexComponent):
    _type = "span"


class FlexImage(FlexComponent):
    _type = "image"


class FlexVideo(FlexComponent):
    _type = "video"


class FlexButton(FlexComponent):
    _type = "button"


class FlexIcon(FlexComponent):
    _type = "icon"


class FlexSeparator(FlexComponent):
    _type = "separator"


class FlexFiller(FlexComponent):
    _type = "filler"


class FlexBubbleStyles(Model):
    pass


class FlexBlockStyle(Model):
    pass


# ============================================================================
# Rich Menu
# ============================================================================
class RichMenuSize(Model):
    pass


class RichMenuBounds(Model):
    pass


class RichMenuArea(Model):
    pass


class RichMenuRequest(Model):
    pass


class RichMenuBulkLinkRequest(Model):
    pass


class RichMenuBulkUnlinkRequest(Model):
    pass


class CreateRichMenuAliasRequest(Model):
    pass


class UpdateRichMenuAliasRequest(Model):
    pass


class RichMenuIdResponse(Model):
    pass


class RichMenuResponse(Model):
    @classmethod
    def from_dict(cls, data):
        return None if data is None else deep_from_dict(cls, data)


class RichMenuListResponse(Model):
    @classmethod
    def from_dict(cls, data):
        obj = super().from_dict(data or {})
        obj.richmenus = [RichMenuResponse.from_dict(m) for m in (data or {}).get("richmenus", [])]
        return obj


class RichMenuAliasResponse(Model):
    pass


class RichMenuAliasListResponse(Model):
    @classmethod
    def from_dict(cls, data):
        obj = super().from_dict(data or {})
        obj.aliases = [RichMenuAliasResponse.from_dict(a) for a in (data or {}).get("aliases", [])]
        return obj


# ============================================================================
# Requests
# ============================================================================
class ReplyMessageRequest(Model):
    pass


class PushMessageRequest(Model):
    pass


class MulticastRequest(Model):
    pass


class BroadcastRequest(Model):
    pass


class NarrowcastRequest(Model):
    pass


class ShowLoadingAnimationRequest(Model):
    pass


# ============================================================================
# Responses（由伺服器 JSON 轉成物件，屬性為 snake_case）
# ============================================================================
class SentMessage(Model):
    pass


class ReplyMessageResponse(Model):
    @classmethod
    def from_dict(cls, data):
        obj = super().from_dict(data or {})
        obj.sent_messages = [SentMessage.from_dict(m) for m in (data or {}).get("sentMessages", [])]
        return obj


class PushMessageResponse(ReplyMessageResponse):
    pass


class UserProfileResponse(Model):
    pass


class MessageQuotaResponse(Model):
    pass


class QuotaConsumptionResponse(Model):
    pass


class ErrorResponse(Model):
    pass


__all__ = [name for name, obj in list(globals().items())
           if isinstance(obj, type) and issubclass(obj, Model)]
