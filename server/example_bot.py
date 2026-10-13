"""
Example: 你的原有 LINE Bot 程式碼 — 幾乎不需要修改！

改動說明：
1. import 從 linebot 換成 localbot
2. LineBotApi 初始化時多傳一個 server_url（指向 app.py 平台）
3. 其餘所有業務邏輯完全不用改

使用方式：
  python my_bot.py
  （會在 localhost:8000 啟動，等待 app.py 轉發 Webhook 給它）
"""
import os
from flask import Flask, request, abort

# ============================================================
# 唯一需要改的：import 來源從 linebot 換成 localbot
# ============================================================
# 原本：
# from linebot import LineBotApi, WebhookHandler
# from linebot.models import *
# from linebot.exceptions import InvalidSignatureError

# 改成：
from localbot import LineBotApi, WebhookHandler
from localbot.exceptions import InvalidSignatureError
from localbot.models import (
    MessageEvent, PostbackEvent,
    TextMessage, ImageMessage, AudioMessage,
    TextSendMessage, ImageSendMessage, AudioSendMessage, StickerSendMessage,
    TemplateSendMessage, ButtonsTemplate, ConfirmTemplate, CarouselTemplate, CarouselColumn,
    PostbackAction, MessageAction,
    FlexSendMessage
)

# ============================================================
# 設定（對應 LINE 的 Channel Access Token 和 Channel Secret）
# ============================================================
# 預設從 app.py 第一次啟動時產生的 .localbot_secrets.json 讀取；也可用環境變數覆寫
from localconfig import CHANNEL_ACCESS_TOKEN, CHANNEL_SECRET

# server_url = 你的 app.py 平台的公網位址（經過 Cloudflare 的 HTTPS 位址）
# LineBotApi 會對這個 URL 發送 reply/push/get_content 請求
PLATFORM_URL = os.environ.get("LOCALBOT_SERVER_URL", "http://localhost:5003")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN, server_url=PLATFORM_URL)
handler = WebhookHandler(CHANNEL_SECRET)


# ============================================================
# 以下是你原本的 LINE Bot 業務邏輯，完全不需要改
# ============================================================

app = Flask(__name__)

@app.route("/callback", methods=['POST'])
def callback():
    """接收來自 app.py 平台轉發的 Webhook 事件（就像接收 LINE 平台的 Webhook）"""
    signature = request.headers.get('X-Line-Signature') or request.headers.get('X-LocalBot-Signature')
    body = request.get_data(as_text=True)
    print(f"[Bot] Received webhook, body length={len(body)}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("[Bot] Invalid signature!")
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    text = event.message.text.strip()
    reply_token = event.reply_token
    user_id = event.source.user_id

    print(f"[Bot] Text from {user_id}: {text}")

    if text.lower() == "buttons":
        buttons_template = ButtonsTemplate(
            thumbnail_image_url=f"{PLATFORM_URL}/media/demo_thumb.png",
            title="選單範例",
            text="請選擇一個操作：",
            actions=[
                PostbackAction(label="執行 Postback", data="action=buy&itemid=101"),
                MessageAction(label="發送訊息", text="你點擊了發送訊息按鈕")
            ]
        )
        line_bot_api.reply_message(reply_token, TemplateSendMessage(alt_text="按鈕選單", template=buttons_template))

    elif text.lower() == "confirm":
        confirm_template = ConfirmTemplate(
            text="您確定要繼續操作嗎？",
            actions=[
                MessageAction(label="是", text="我選擇了：是"),
                MessageAction(label="否", text="我選擇了：否")
            ]
        )
        line_bot_api.reply_message(reply_token, TemplateSendMessage(alt_text="確認框", template=confirm_template))

    elif text.lower() == "carousel":
        carousel_template = CarouselTemplate(
            columns=[
                CarouselColumn(
                    thumbnail_image_url=f"{PLATFORM_URL}/media/thumb1.png",
                    title="商品 A",
                    text="NT$ 500",
                    actions=[
                        PostbackAction(label="購買 A", data="buy=A"),
                        MessageAction(label="詢問", text="我想詢問商品 A")
                    ]
                ),
                CarouselColumn(
                    thumbnail_image_url=f"{PLATFORM_URL}/media/thumb2.png",
                    title="商品 B",
                    text="NT$ 800",
                    actions=[
                        PostbackAction(label="購買 B", data="buy=B"),
                        MessageAction(label="詢問", text="我想詢問商品 B")
                    ]
                )
            ]
        )
        line_bot_api.reply_message(reply_token, TemplateSendMessage(alt_text="商品輪播", template=carousel_template))

    elif text.lower() == "sticker":
        line_bot_api.reply_message(
            reply_token,
            [
                TextSendMessage(text="這是一張貼圖回覆："),
                StickerSendMessage(package_id="1", sticker_id="1")
            ]
        )

    elif text.lower() == "flex":
        flex_content = {
            "type": "bubble",
            "header": {
                "type": "box", "layout": "vertical",
                "contents": [{"type": "text", "text": "LocalBot Flex 訊息", "weight": "bold", "size": "lg", "color": "#1DB446"}]
            },
            "body": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "這是一則原生渲染的 Flex 訊息卡片！", "wrap": True, "size": "md"},
                    {"type": "text", "text": "支援巢狀排列、自訂顏色與按鈕互動。", "wrap": True, "size": "sm", "color": "#666666"}
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical",
                "contents": [{"type": "button", "action": {"type": "postback", "label": "點我測試", "data": "flex_click=true"}}]
            }
        }
        line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="Flex 測試卡片", contents=flex_content))

    elif text.lower() == "push":
        line_bot_api.reply_message(reply_token, TextSendMessage(text="即將向您發送一條 Push 訊息..."))
        line_bot_api.push_message(user_id, TextSendMessage(text="【Push 通知】這是主動推播的訊息！"))

    else:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=f"收到您的訊息：{text}\n\n可輸入下列關鍵字測試特殊回覆：\n• buttons (按鈕選單)\n• confirm (確認框)\n• carousel (輪播卡片)\n• flex (Flex 訊息)\n• sticker (貼圖)\n• push (主動推播)")
        )


@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    message_id = event.message.id
    reply_token = event.reply_token

    message_content = line_bot_api.get_message_content(message_id)
    image_bytes = message_content.content
    byte_size = len(image_bytes) if image_bytes else 0

    print(f"[Bot] Image {message_id}, size: {byte_size} bytes")

    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=f"收到圖片！大小為 {byte_size} 位元組，已成功讀取。")
    )


@handler.add(MessageEvent, message=AudioMessage)
def handle_audio_message(event):
    message_id = event.message.id
    duration = event.message.duration
    reply_token = event.reply_token

    message_content = line_bot_api.get_message_content(message_id)
    audio_bytes = message_content.content
    byte_size = len(audio_bytes) if audio_bytes else 0

    print(f"[Bot] Audio {message_id}, duration: {duration}ms, size: {byte_size} bytes")

    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=f"收到語音訊息！時長: {duration}毫秒，檔案大小: {byte_size} 位元組。")
    )


@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    reply_token = event.reply_token
    print(f"[Bot] Postback from {event.source.user_id}: {data}")

    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=f"已收到 Postback 操作！\n回傳資料: {data}")
    )


# ============================================================
# 啟動你的 Bot（預設跑在 127.0.0.1:9000，等待 app.py 平台轉發 Webhook）
# 若 Bot 與 app.py 不在同一台機器，設定 LOCALBOT_BOT_HOST=0.0.0.0
# ============================================================
BOT_PORT = int(os.environ.get("LOCALBOT_BOT_PORT", "9000"))
BOT_HOST = os.environ.get("LOCALBOT_BOT_HOST", "127.0.0.1")

if __name__ == "__main__":
    print(f"[Bot] Starting on port {BOT_PORT}")
    print(f"[Bot] Platform URL: {PLATFORM_URL}")
    print(f"[Bot] Webhook endpoint: http://localhost:{BOT_PORT}/callback")
    app.run(host=BOT_HOST, port=BOT_PORT, debug=False)
