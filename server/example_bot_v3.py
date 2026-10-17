"""
Example: line-bot-sdk v3 寫法的 Bot，改用 LocalBot 平台。

改動說明（與官方 v3 範例相比）：
1. import 從 linebot.v3 換成 localbot.v3
2. Configuration 多傳一個 host（指向 app.py 平台）
3. 其餘業務邏輯不用改

使用方式：
  python example_bot_v3.py
  （預設在 127.0.0.1:9000 啟動，等待 app.py 轉發 Webhook）
"""
import os

from flask import Flask, abort, request

# ============================================================
# 原本：
# from linebot.v3 import WebhookHandler
# from linebot.v3.exceptions import InvalidSignatureError
# from linebot.v3.messaging import ...
# from linebot.v3.webhooks import ...
# 改成：
# ============================================================
from localbot.v3 import WebhookHandler
from localbot.v3.exceptions import InvalidSignatureError
from localbot.v3.messaging import (
    ApiClient,
    CameraRollAction,
    Configuration,
    ImagemapArea,
    ImagemapBaseSize,
    ImagemapMessage,
    MessageImagemapAction,
    URIImagemapAction,
    DatetimePickerAction,
    LocationAction,
    MessageAction,
    MessagingApi,
    MessagingApiBlob,
    PostbackAction,
    PushMessageRequest,
    QuickReply,
    QuickReplyItem,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)
from localbot.v3.webhooks import (
    FileMessageContent,
    FollowEvent,
    ImageMessageContent,
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
    VideoMessageContent,
)

# 預設從 app.py 第一次啟動時產生的 .localbot_secrets.json 讀取；也可用環境變數覆寫
from localconfig import CHANNEL_ACCESS_TOKEN, CHANNEL_SECRET

PLATFORM_URL = os.environ.get("LOCALBOT_SERVER_URL", "http://localhost:5003")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN, host=PLATFORM_URL)
handler = WebhookHandler(CHANNEL_SECRET)

app = Flask(__name__)


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature") or request.headers.get("X-LocalBot-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


def reply(reply_token, *messages):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message_with_http_info(
            ReplyMessageRequest(reply_token=reply_token, messages=list(messages))
        )


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    text = event.message.text.strip()

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        # 在 App 顯示「輸入中」動畫（5～60 秒，5 的倍數；收到回覆後自動消失）
        api.show_loading_animation(ShowLoadingAnimationRequest(chat_id=event.source.user_id, loading_seconds=5))

        if text.lower() == "quick":
            quick_reply = QuickReply(items=[
                QuickReplyItem(action=MessageAction(label="好喝", text="我覺得好喝")),
                QuickReplyItem(action=PostbackAction(label="再來一杯", data="drink=more", display_text="再來一杯")),
                QuickReplyItem(action=DatetimePickerAction(label="預約時間", data="action=book", mode="datetime")),
                QuickReplyItem(action=CameraRollAction(label="傳照片")),
                QuickReplyItem(action=LocationAction(label="傳位置")),
            ])
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="今天的咖啡如何？（點下方的快速回覆）", quick_reply=quick_reply)],
            ))
        elif text.lower() == "imagemap":
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[ImagemapMessage(
                    base_url=f"{PLATFORM_URL}/imagemap/demo",
                    alt_text="圖片地圖範例",
                    base_size=ImagemapBaseSize(width=1040, height=520),
                    actions=[
                        MessageImagemapAction(text="你點了左邊", area=ImagemapArea(x=0, y=0, width=520, height=520)),
                        URIImagemapAction(link_uri="https://github.com/kochunchung/localbot",
                                          area=ImagemapArea(x=520, y=0, width=520, height=520)),
                    ],
                )],
            ))
        elif text.lower() == "push":
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, messages=[TextMessage(text="即將發送 Push 訊息…")]))
            api.push_message(PushMessageRequest(
                to=event.source.user_id, messages=[TextMessage(text="【Push 通知】這是主動推播的訊息！")]))
        else:
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"（v3）收到：{text}\n\n試試輸入：quick、imagemap、push")],
            ))


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    with ApiClient(configuration) as api_client:
        content = MessagingApiBlob(api_client).get_message_content(event.message.id)
    reply(event.reply_token, TextMessage(text=f"收到圖片，大小 {len(content)} 位元組。"))


@handler.add(MessageEvent, message=VideoMessageContent)
def handle_video(event):
    with ApiClient(configuration) as api_client:
        content = MessagingApiBlob(api_client).get_message_content(event.message.id)
    reply(event.reply_token, TextMessage(text=f"收到影片，長度 {event.message.duration} 毫秒，大小 {len(content)} 位元組。"))


@handler.add(MessageEvent, message=FileMessageContent)
def handle_file(event):
    with ApiClient(configuration) as api_client:
        content = MessagingApiBlob(api_client).get_message_content(event.message.id)
    reply(event.reply_token, TextMessage(text=f"收到檔案「{event.message.file_name}」，大小 {len(content)} 位元組。"))


@handler.add(PostbackEvent)
def handle_postback(event):
    params = event.postback.params or {}
    extra = f"\n選擇的時間：{params}" if params else ""
    reply(event.reply_token, TextMessage(text=f"Postback：{event.postback.data}{extra}"))


@handler.add(FollowEvent)
def handle_follow(event):
    reply(event.reply_token, TextMessage(text="歡迎使用 LocalBot！"))


BOT_PORT = int(os.environ.get("LOCALBOT_BOT_PORT", "9000"))
BOT_HOST = os.environ.get("LOCALBOT_BOT_HOST", "127.0.0.1")

if __name__ == "__main__":
    print(f"[Bot v3] Starting on {BOT_HOST}:{BOT_PORT}, platform={PLATFORM_URL}")
    app.run(host=BOT_HOST, port=BOT_PORT, debug=False)
