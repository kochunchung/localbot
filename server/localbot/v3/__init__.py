"""
localbot.v3 —— 對應 line-bot-sdk v3（linebot.v3）的寫法。

把 import 的 `linebot.v3` 換成 `localbot.v3`，並在 Configuration 指定 host 即可：

    from localbot.v3 import WebhookHandler
    from localbot.v3.exceptions import InvalidSignatureError
    from localbot.v3.messaging import (
        Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage,
    )
    from localbot.v3.webhooks import MessageEvent, TextMessageContent

    configuration = Configuration(access_token=TOKEN, host="http://localhost:5003")
"""
from .webhook import WebhookHandler, WebhookParser, WebhookPayload

__all__ = ["WebhookHandler", "WebhookParser", "WebhookPayload"]
