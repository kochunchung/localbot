<div align="center">

# LocalBot

**自架的 LINE Bot 平台 — 你的 Bot 程式碼幾乎不用改，就能脫離 LINE 官方平台運作**

Self-hosted, LINE-Messaging-API-compatible chat platform + Flutter client.
Run your existing `line-bot-sdk` bot on your own server by changing 3 import lines.

[![Server Tests](https://github.com/kochunchung/localbot/actions/workflows/server-tests.yml/badge.svg)](https://github.com/kochunchung/localbot/actions/workflows/server-tests.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Flutter](https://img.shields.io/badge/Flutter-3.x-02569B)
![License](https://img.shields.io/badge/License-MIT-green)

[介紹網站](https://kochunchung.github.io/localbot/) ·
[下載 Android App](https://github.com/kochunchung/localbot/releases/latest) ·
[快速開始](#-五分鐘快速開始)

</div>

---

### English summary

LocalBot is a drop-in replacement for the LINE Messaging API that you host yourself.
It has two parts: a **Python platform server** (`server/`) that plays the role of the LINE
platform — receiving messages from the app, signing and forwarding webhooks to your bot,
and accepting `reply_message` / `push_message` calls — and a **Flutter mobile app**
(`flutter_app/`) with a clean Material 3 chat UI (light & dark) that renders text, images, voice, stickers,
Buttons / Confirm / Carousel templates and basic Flex messages.
Your bot keeps its `line-bot-sdk`-style code; only the imports and `server_url` change.
No message quotas, no monthly fees, and all data stays on your own machine.

---

## 💡 為什麼做 LocalBot？

LINE 官方帳號的免費訊息額度有限、推播要計費，個人或公司內部使用時常常被卡住。
很多人已經寫好了 LINE Bot（股價查詢、內部通知、AI 助理……），卻只能在 LINE 的框架下運作。

**LocalBot 讓你把整套 LINE Bot 搬回自己的伺服器：**

| | LINE 官方平台 | LocalBot |
|---|---|---|
| 訊息額度 | 有免費上限，超過要付費 | **無上限** |
| 資料存放 | LINE 伺服器 | **你自己的主機（SQLite）** |
| 現有 Bot 程式碼 | — | **改 3 行 import 就能跑** |
| 用戶端 | LINE App | 開源 Flutter App（Android / iOS） |
| 適合 | 面向大眾的官方帳號 | 個人工具、家庭、公司內網、教學、離線測試 |

## ✨ 功能

- 🎨 Material 3 介面、自動深色模式、可自訂品牌色與 Bot 名稱
- 💬 文字訊息雙向對話、離線訊息佇列（手機離線也不漏訊息）
- 📷 圖片傳送（拍照 / 相簿）＋全螢幕檢視
- 🎤 語音錄製與播放
- 📍 地圖選點分享位置（OpenStreetMap）
- 😊 自訂貼圖包（放進 `server/media/stickers/<packageId>/` 即可）
- 📋 `TemplateSendMessage`：Buttons / Confirm / Carousel
- 🧩 `FlexSendMessage` 基本渲染
- 🔁 `PostbackAction` / `MessageAction` 互動
- ⚡ Socket.IO 即時推播
- 🔒 安全機制：Webhook HMAC-SHA256 簽名、Bot API Bearer Token、App 端簽名與每位使用者存取憑證

## 🏗 架構

```
┌──────────────────┐  POST /callback   ┌───────────────────────┐  POST webhook   ┌──────────────────┐
│  Flutter 手機 App │ ───(App 簽名)───► │  server/app.py         │ ──(Channel 簽名)─► │  你的 Bot 程式     │
│  文字/圖片/語音    │                   │  扮演「LINE 平台」       │                   │  (line-bot-sdk 風格)│
│                  │ ◄──Socket.IO────── │  port 5003             │ ◄──reply / push──  │  port 9000        │
└──────────────────┘   (token 驗證)     └───────────────────────┘  (Bearer Token)   └──────────────────┘
```

## 🚀 五分鐘快速開始

### 1. 啟動平台

```bash
git clone https://github.com/kochunchung/localbot.git
cd localbot/server
pip install -r requirements.txt
python app.py
```

第一次啟動會自動產生三組隨機金鑰，存在 `server/.localbot_secrets.json`（已被 `.gitignore` 排除）：

| 金鑰 | 用途 | 交給誰 |
|---|---|---|
| `CHANNEL_SECRET` | 平台 → Bot 的 Webhook 簽名 | 只給 Bot 程式 |
| `CHANNEL_ACCESS_TOKEN` | Bot → 平台 API 的 Bearer Token | 只給 Bot 程式 |
| `APP_SECRET` | App → 平台 的簽名金鑰 | 填在手機 App 設定頁 |

也可以用環境變數指定，範例見 [`server/.env.example`](server/.env.example)。

### 2. 啟動範例 Bot

```bash
cd server
python example_bot.py      # 跑在 127.0.0.1:9000
```

### 3. 安裝 App

- Android：到 [Releases](https://github.com/kochunchung/localbot/releases/latest) 下載 APK 安裝
- 或自行編譯：
  ```bash
  cd flutter_app/localbot_app
  flutter pub get
  flutter build apk --release --dart-define=LOCALBOT_SERVER_URL=https://your-domain.example.com
  ```

開啟 App → 設定 → 填入 **Server URL** 與 **App Secret** → 儲存，就能開始對話。

### 4. 對外公開（選用）

App 預設只允許 HTTPS 連線。建議用 Cloudflare Tunnel、Nginx + Let's Encrypt 等方式，
把 `localhost:5003` 以 HTTPS 對外，並確認 WebSocket 已開啟。

## 🔄 把現有 LINE Bot 搬過來

```python
# 原本
# from linebot import LineBotApi, WebhookHandler
# from linebot.models import *
# from linebot.exceptions import InvalidSignatureError

# 改成
from localbot import LineBotApi, WebhookHandler
from localbot.models import *
from localbot.exceptions import InvalidSignatureError

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN, server_url="https://your-domain.example.com")
handler = WebhookHandler(CHANNEL_SECRET)

# ===== 以下業務邏輯完全不用改 =====
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"你說了：{event.message.text}"))
```

支援的 API：`reply_message`、`push_message`、`get_message_content`、`get_profile`、
`get_group_member_profile`、`get_room_member_profile`。

## ⚙️ 設定（環境變數）

| 變數 | 預設值 | 說明 |
|---|---|---|
| `LOCALBOT_SERVER_URL` | `http://localhost:5003` | 平台對外網址（用來產生媒體檔 URL） |
| `LOCALBOT_PORT` | `5003` | app.py 監聽埠 |
| `LOCALBOT_BOT_WEBHOOK_URL` | `http://localhost:9000/callback` | 你的 Bot Webhook 位址 |
| `LOCALBOT_CHANNEL_SECRET` / `_ACCESS_TOKEN` / `_APP_SECRET` | 自動產生 | 見上方金鑰表 |
| `LOCALBOT_DEBUG` | `false` | 只在本機開發時開啟 |
| `LOCALBOT_MAX_UPLOAD_MB` | `20` | 上傳檔案大小上限 |
| `LOCALBOT_CORS_ORIGINS` | `*` | Socket.IO 允許來源，逗號分隔 |

## 🧪 測試

```bash
cd server
python -m pytest -q tests
```

## 🔐 安全性說明

- 金鑰檔 `.localbot_secrets.json`、資料庫、上傳媒體都已列入 `.gitignore`，請勿上傳。
- 持有 `APP_SECRET` 的人都能使用這個平台，請只分享給信任的使用者；若外洩，刪除金鑰檔或換新的環境變數即可全部失效。
- 正式環境請保持 `LOCALBOT_DEBUG=false`，並透過 HTTPS 對外。
- 發現安全問題請開 Issue 或私訊作者，不要公開漏洞細節。

## 🗺 Roadmap

- [ ] 群組 / 多人聊天室
- [ ] Rich Menu
- [ ] 完整 Flex Message 元件
- [ ] Docker 一鍵部署
- [ ] Web 版用戶端

歡迎 PR 與 Issue！

## 📄 授權與聲明

本專案採用 [MIT License](LICENSE)。

LocalBot 是獨立的開源專案，與 LINE Corporation / LY Corporation 無任何關係。
「LINE」為其所有者之商標；本專案僅相容其公開的 Messaging API 介面設計，
不使用、也不連線至 LINE 的任何服務。
