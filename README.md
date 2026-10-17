<div align="center">

# LocalBot

**自架的 LINE Bot 平台 — 你的 Bot 程式碼幾乎不用改，就能脫離 LINE 官方平台運作**

Self-hosted, LINE-Messaging-API-compatible chat platform + Flutter client.
Run your existing `line-bot-sdk` bot on your own server by changing 3 import lines.

[![Server Tests](https://github.com/kochunchung/localbot/actions/workflows/server-tests.yml/badge.svg)](https://github.com/kochunchung/localbot/actions/workflows/server-tests.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Flutter](https://img.shields.io/badge/Flutter-3.x-02569B)
![License](https://img.shields.io/badge/License-MIT-green)
![Server](https://img.shields.io/badge/server-v3.1.0-4f46e5)
![App](https://img.shields.io/badge/app-v1.4.0-4f46e5)

[介紹網站](https://kochunchung.github.io/localbot/) ·
[下載 Android App](https://github.com/kochunchung/localbot/releases/latest) ·
[快速開始](#-五分鐘快速開始) ·
[更新紀錄](CHANGELOG.md)

</div>

---

### English summary

LocalBot is a drop-in replacement for the LINE Messaging API that you host yourself.
It has two parts: a **Python platform server** (`server/`) that plays the role of the LINE
platform — receiving messages from the app, signing and forwarding webhooks to your bot,
and accepting `reply_message` / `push_message` calls — and a **Flutter mobile app**
(`flutter_app/`) with a clean Material 3 chat UI (light & dark) that renders text, images, voice, stickers,
Buttons / Confirm / Carousel templates and basic Flex messages.
The server also ships a web admin console, multi-bot support with invite codes, webhook retries,
scheduled pushes and optional AI-generated scheduled messages (Claude / OpenAI).
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
- 🎬 影片傳送與播放、📎 檔案傳送與下載（PDF、Office、zip 等）
- 🎤 語音錄製與播放
- 📍 地圖選點分享位置（OpenStreetMap）
- 😊 自訂貼圖包（放進 `server/media/stickers/<packageId>/` 即可）
- 📋 `TemplateSendMessage`：Buttons / Confirm / Carousel
- 🧩 `FlexSendMessage`：box / text / span / image / icon / button / separator / filler / video，支援 flex、spacing、margin、padding、漸層背景、圓角、絕對定位、輪播等常用屬性
- 🗺 `ImagemapSendMessage`：可點擊區域、內嵌影片（圖片只需放一張）
- 📱 Rich Menu 圖文選單：預設選單、個別使用者選單、別名切換（richmenuswitch）
- 👋 follow / unfollow 事件：首次加入自動送 follow；App 可封鎖 / 解除封鎖 Bot
- 🔁 `PostbackAction` / `MessageAction` / `URIAction` / `DatetimePickerAction` / `ClipboardAction` 互動
- ⚡ Quick Reply 快速回覆（訊息、Postback、連結、日期時間、相機、相簿、位置）
- ⌛ 「輸入中」動畫（`show_loading_animation`）
- 🐍 同時支援 line-bot-sdk **v1/v2**（`localbot`）與 **v3**（`localbot.v3`）寫法
- ⚡ Socket.IO 即時推播；App 送出訊息不必等 Bot 處理完（背景轉送，送不到才標示）
- 💬 長按訊息：回覆（引用，Bot 收到 `quotedMessageId`）、複製、刪除本機紀錄；「以下為未讀訊息」分隔線、跳到最新按鈕
- 🖼 每個 Bot 可在後台上傳自己的頭像
- 🤖 **多 Bot**：一台平台可以同時服務多個 Bot，每個 Bot 有自己的 Webhook、金鑰、好友與 Rich Menu；一位使用者可以加入多個 Bot
- 🎟 **邀請碼 / QR Code 加入**：管理員在後台產生邀請碼（可限次數、期限），手機掃描或輸入就能加入；每支手機領到自己專屬的金鑰，可在後台單獨撤銷
- 🛠 內建網頁**管理後台**（`/admin`）：儀表板、Bot 與邀請碼、使用者管理、訊息紀錄與發送、Rich Menu 管理、金鑰檢視、排程推播、Webhook 日誌與重送
- ⏰ 排程推播（單次／每日／每週／每月），內容可由 **Claude / OpenAI 自動產生**（可上網搜尋，例如每天整理昨天的美股）
- 🔁 Webhook 自動重試與日誌：Bot 暫時掛掉不漏訊息，後台可查詢與重送
- 🔒 安全機制：Webhook HMAC-SHA256 簽名、每個 Bot 獨立的 Bearer Token、每支手機獨立的金鑰（伺服器只存雜湊）

## 🏗 架構

```
┌──────────────────┐  POST /callback   ┌───────────────────────┐  POST webhook   ┌──────────────────┐
│  Flutter 手機 App │ ──(手機專屬金鑰)──► │  server/app.py         │ ──(Channel 簽名)─► │  Bot A（你的程式）  │
│  可加入多個 Bot    │   destination=Bot  │  扮演「LINE 平台」       │                   │  (line-bot-sdk 風格)│
│  文字/圖片/語音    │ ◄──Socket.IO────── │  port 5003             │ ◄──reply / push──  ├──────────────────┤
└──────────────────┘   (金鑰驗證)        └───────────────────────┘  (各 Bot 的 Token) │  Bot B …          │
                                                                                      └──────────────────┘
```

### 專案結構

```
localbot/
├── server/                  平台伺服器（Python / Flask / Flask-SocketIO / SQLite）
│   ├── app.py               主程式：/callback、/v2/bot/*、/api/v1/bot/*、Socket.IO
│   ├── database.py          資料庫與自動遷移
│   ├── admin_*.py, admin_ui/ 管理後台（API 與單頁介面）
│   ├── scheduled_push.py    排程推播；ai_generate.py：AI 產生訊息
│   ├── webhook_delivery.py  Webhook 轉送、重試與日誌；workers.py：背景工作
│   ├── localbot/            與 line-bot-sdk 相容的 SDK（v1/v2 與 v3）
│   ├── example_bot.py, example_bot_v3.py, setup_richmenu.py
│   └── tests/               pytest 測試
├── flutter_app/localbot_app/ 手機 App（Flutter，Android / iOS）
├── docs/                    GitHub Pages 介紹網站
└── .github/workflows/       CI：伺服器測試、iOS 編譯（未簽章）
```

## 🚀 五分鐘快速開始

### 1. 啟動平台

```bash
git clone https://github.com/kochunchung/localbot.git
cd localbot/server
pip install -r requirements.txt
python app.py
```

第一次啟動會自動建立一個「預設 Bot」，並產生它的兩組隨機金鑰，存在 `server/.localbot_secrets.json`（已被 `.gitignore` 排除）：

| 金鑰 | 用途 | 交給誰 |
|---|---|---|
| `CHANNEL_SECRET` | 平台 → Bot 的 Webhook 簽名 | 只給 Bot 程式 |
| `CHANNEL_ACCESS_TOKEN` | Bot → 平台 API 的 Bearer Token（平台靠它辨識是哪個 Bot） | 只給 Bot 程式 |

要接第二個、第三個 Bot？到後台「Bot 與邀請碼」新增，每個 Bot 會有自己的 Channel Secret / Access Token / Webhook 網址。
**手機 App 不再使用共用金鑰**：使用者用管理員產生的邀請碼加入，第一次加入時平台發一把這支手機專屬的金鑰。

也可以用環境變數指定預設 Bot，範例見 [`server/.env.example`](server/.env.example)（這些設定只在第一次啟動建立預設 Bot 時使用，之後請到後台修改）。

同時會產生**後台管理密碼**（16 字元），只在第一次啟動時顯示在主控台，之後可在金鑰檔的 `ADMIN_PASSWORD` 查看。
登入網址：`<你的網址>/admin`（本機是 http://localhost:5003/admin）。

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

開啟 App，用邀請碼加入 Bot：

1. 在後台「Bot 與邀請碼」選一個 Bot →「產生邀請碼」（可設定可用次數與有效期限），畫面會顯示邀請碼、邀請連結（`localbot://join?server=…&code=…`）和 QR Code。
2. 手機開啟 App →「掃描邀請 QR Code」，或輸入邀請碼與伺服器網址，按「加入」。點到邀請連結也會自動帶入。
3. 加入後就會出現在 Bot 清單，點進去開始對話。想加入其他 Bot，按右上角「加入 Bot」再輸入另一組邀請碼即可（同一支手機、同一把金鑰）。
4. 管理員可以在後台「使用者」頁撤銷某支手機的金鑰；被撤銷的手機會要求重新輸入新的邀請碼，原本的對話紀錄保留。

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

支援的 API：`reply_message`、`push_message`、`multicast`、`broadcast`、`narrowcast`、
`get_message_content`、`get_profile`、`get_group_member_profile`、`get_room_member_profile`、
`get_message_quota`、`get_message_quota_consumption`、`show_loading_animation`。

### line-bot-sdk v3 寫法

```python
# 原本
# from linebot.v3 import WebhookHandler
# from linebot.v3.exceptions import InvalidSignatureError
# from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
# from linebot.v3.webhooks import MessageEvent, TextMessageContent

# 改成
from localbot.v3 import WebhookHandler
from localbot.v3.exceptions import InvalidSignatureError
from localbot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from localbot.v3.webhooks import MessageEvent, TextMessageContent

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN, host="https://your-domain.example.com")
handler = WebhookHandler(CHANNEL_SECRET)

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=event.message.text)],
        ))
```

完整範例見 `server/example_bot_v3.py`（輸入 `quick` 可測試 Quick Reply）。
`MessagingApi` 支援 reply / push / multicast / broadcast / narrowcast / get_profile /
show_loading_animation / get_message_quota；`MessagingApiBlob.get_message_content` 可下載媒體。

> 平台也提供與 LINE 相同路徑的 `/v2/bot/*` 端點。理論上官方 `line-bot-sdk` v3 只要把
> `Configuration(host=...)` 指向 LocalBot 也能呼叫 reply / push，但未經完整測試，建議使用 `localbot.v3`。

### Imagemap

LINE 要求同一張圖準備 240 / 300 / 460 / 700 / 1040 五種寬度；LocalBot 只要把**一張**圖放到
`server/media/imagemap/<名稱>/`，`baseUrl` 設為 `https://你的網域/imagemap/<名稱>` 即可。
名稱 `demo` 為內建示範圖（範例 Bot 輸入 `imagemap`）。

### Rich Menu

```bash
cd server
python setup_richmenu.py            # 建立兩頁示範選單（可互相切換）並設為預設
python setup_richmenu.py --image main.png --image2 page2.png   # 使用自己的圖片（2500x843，1 MB 內）
python setup_richmenu.py --clear    # 刪除所有選單
```

`create_rich_menu`、`set_rich_menu_image`、`set_default_rich_menu`、`link_rich_menu_to_user`、
別名（alias）等 API 與官方 SDK 相同（v1 與 v3 寫法皆可）。App 會在輸入列左側顯示選單按鈕，
Bot 變更選單時即時更新。選單圖片請自行設計，不要使用 LINE 的圖示或配色。

### follow / unfollow

- 使用者第一次用邀請碼加入某個 Bot 時，平台自動對那個 Bot 送出 `follow` 事件，Bot 可以用它的 `reply_token` 回歡迎訊息。
- App 的 Bot 設定頁可「封鎖這個 Bot」：送出 `unfollow`，之後 Bot 的訊息不會送達、broadcast 會略過；
  解除封鎖會送出 `follow`（`follow.isUnblocked = true`）。

### LocalBot 的差異

- narrowcast 沒有受眾資料，會送給所有已註冊使用者。
- 訊息額度固定回傳 `none`（無上限）。
- 每次請求最多 5 則訊息、Quick Reply 最多 13 個按鈕（與 LINE 相同），超過會回 400。
- Bot 可以傳送檔案訊息（`FileSendMessage` / v3 `FileMessage`），這是 LocalBot 的擴充功能，LINE 官方不支援。
- Imagemap 圖片只需一張；Rich Menu 圖片不檢查實際像素尺寸，請自行確認與 `size` 相符。
- Bot 頭像在後台「Bot 與邀請碼 → 編輯」上傳（PNG / JPEG / WebP，1 MB 以內），App 的 Bot 清單與聊天室會顯示；圖片放在 `server/media/avatars/`，網址 `/avatars/<檔名>` 不需登入即可讀取（與 LINE 的頭像相同）。
- 使用者在 App 長按訊息選「回覆」時，文字訊息事件會帶 `quotedMessageId`（被引用訊息的 id），`localbot` 與 `localbot.v3` 都可用 `event.message.quoted_message_id` 讀取。

## 🛠 管理後台

打開 `<你的網址>/admin`，用管理員密碼登入：

| 頁面 | 功能 |
|---|---|
| 儀表板 | 使用者數、線上人數、24 小時訊息量、7 天圖表、離線佇列、各 Bot 的 Webhook 連線測試（可依 Bot 篩選） |
| Bot 與邀請碼 | 新增 / 修改 / 停用 / 刪除 Bot、查看與重新產生各 Bot 的金鑰、測試 Webhook；產生邀請碼（次數、期限）並顯示 QR Code，撤銷或刪除邀請碼 |
| 使用者 | 搜尋、改名、依 Bot 查看好友關係、封鎖 / 解除封鎖（針對某個 Bot）、撤銷 / 刪除手機金鑰、查看對話、以 Bot 身分傳訊、指定 Rich Menu |
| 訊息紀錄 | 依 Bot、內容、使用者、方向、類型搜尋；點開看完整 JSON |
| 發送訊息 | 選一個 Bot，對單一使用者或該 Bot 的全體好友廣播文字訊息 |
| Rich Menu | 每個 Bot 各自管理：新增、上傳圖片、設為預設、綁定使用者、別名管理、刪除 |
| 排程推播 | 單次／每日／每週／每月自動推播；內容可以是文字或任意 LINE 訊息 JSON，對象可選全體或指定使用者；立即執行、啟用／停用、執行紀錄 |
| Webhook 日誌 | 每次轉送給 Bot 的結果、每次嘗試的狀態碼與耗時、事件內容；失敗可手動重送，或一鍵重送全部失敗項目 |
| 金鑰與設定 | 後台密碼、伺服器資訊；各 Bot 金鑰在「Bot 與邀請碼」遮罩顯示（再輸入密碼才能看完整內容），重新產生立即生效 |

安全設計：單一頁面、無外部資源、嚴格的 Content-Security-Policy；登入後使用 HttpOnly + SameSite=Strict Cookie，
所有變更操作都要 CSRF token；登入失敗有次數限制；顯示金鑰、重新產生金鑰、改密碼都需要再次輸入密碼；
更換密碼後其他裝置會立刻登出。若不需要後台，設定 `LOCALBOT_ADMIN_ENABLED=false` 即可完全不載入。

> 後台對外公開時務必走 HTTPS，並使用夠長的密碼；也可以在反向代理（Nginx / Cloudflare Access）再加一層保護。

### 排程推播

- 時間以**伺服器本機時區**計算（頁面會顯示目前伺服器時間與時區）；單次排程則是絕對時間。每月選 29～31 日時，沒有該日的月份會改在月底執行。
- 每次執行前會先把「下次執行時間」推進，所以同一個時間點最多執行一次。伺服器停機錯過的排程，超過寬限時間（預設 60 分鐘）就**不補送**，在紀錄標為「錯過」，之後照常執行。
- 「立即執行」不會改變原本的排程時間。全體廣播會略過已封鎖的使用者；指定使用者中已封鎖或不存在的會計入「略過」。
- 排程由背景執行緒處理，伺服器必須持續運作；每個排程保留最近 50 筆執行紀錄。

#### 🤖 AI 產生的排程訊息

排程的「訊息內容」選 **AI 產生**：每次執行時，平台先把你寫的指示交給 Claude 或 OpenAI，再把 AI 的回答當成文字訊息送出。例如每天早上 8 點：

> 請搜尋 {yesterday} 美股收盤資訊，整理三大指數漲跌、表現突出的個股與重要新聞，最後給一句今日觀察重點。

- **金鑰**：後台「設定 → AI 金鑰」貼上 [Anthropic](https://console.anthropic.com/settings/keys) 或 [OpenAI](https://platform.openai.com/api-keys) 的 API 金鑰（存在 `.localbot_secrets.json`），或設定環境變數 `LOCALBOT_ANTHROPIC_API_KEY` / `LOCALBOT_OPENAI_API_KEY`。AI 服務依用量另外收費。
- **上網搜尋**：勾選「允許 AI 上網搜尋」才能取得股價、新聞、天氣等最新資料（Claude 使用 web search 工具，OpenAI 使用 Responses API 的 `web_search`）。
- **變數**：`{today}`、`{yesterday}`、`{weekday}`、`{now}`，以伺服器時區計算。
- **試產生一次**：在排程視窗直接預覽 AI 的回答，不會傳給任何人。
- 每次執行只呼叫 AI 一次，同樣內容送給所有對象；AI 失敗時不會送出，原因記在「紀錄」。AI 呼叫在背景進行，不會卡住其他排程。
- 進階 JSON 模式也可直接寫 `{"type": "ai", "provider": "claude", "prompt": "...", "webSearch": true, "model": "（選填）", "maxChars": 1200}`，和其他 LINE 訊息混在一起。

### Webhook 重試與日誌

平台轉送事件給 Bot 時，每一次都會記錄（狀態：成功／等待重試／已放棄）：

- **自動重試**：連線失敗、逾時、HTTP 5xx／408／425／429 會依 `LOCALBOT_WEBHOOK_RETRY_DELAYS`（預設 10 秒、1 分、5 分、30 分）遞增重試；其他 4xx 代表 Bot 拒絕處理，不重試。重試狀態存在資料庫，伺服器重啟後會繼續。
- **對 App 的回應**：Bot 暫時失敗但已排入重試時，`/callback` 仍回 `200`（並加上標頭 `X-LocalBot-Delivery: queued`），App 不需要重傳訊息；不會重試的失敗仍回 `502`。
- **快速送出（App 1.4 起）**：App 帶標頭 `X-LocalBot-Async: 1` 時，平台存好訊息就立刻回 `200`（`X-LocalBot-Delivery: async`），再於背景依序轉送給 Bot（同一位使用者的訊息保持送出順序）；最後確定送不到時，以 Socket.IO 事件 `delivery_failed`（`{botId, messageIds, reason}`）通知 App 把訊息標成「傳送失敗」。舊版 App 不帶此標頭，維持原本的同步行為。
- **重送的事件**：沿用同一個 `webhookEventId`，並帶 `deliveryContext.isRedelivery = true`。Bot 若曾處理成功卻沒及時回應，可以用 `webhookEventId` 去重（與 LINE 平台行為一致）。
- **手動重送**：後台日誌可單筆重送或「全部重送失敗項目」；手動重送失敗不會再自動重試。
- 紀錄保留 `LOCALBOT_LOG_RETENTION_DAYS`（預設 30）天，等待重試中的不會被清掉。

> 用 `python app.py` 啟動時背景工作會自動啟動；若改用 gunicorn 等方式，請在啟動時呼叫一次 `app.start_background_workers()`（並只用單一 worker 程序）。

## ⬆️ 升級

### 從 v3.0 / App 1.3.x 升到 v3.1 / App 1.4

- **不需要手動遷移**：資料庫啟動時自動新增 `bots.avatar` 欄位。升級前仍建議備份 `localbot.db`。
- 伺服器：覆蓋 `server/` 的程式（注意新增了 `ai_generate.py`），保留 `localbot.db`、`.localbot_secrets.json`、`media/`，重新啟動即可。
- App：安裝 1.4.0 後才會使用「快速送出」、頭像、引用回覆；舊版 App 仍可連線，行為不變。
- 要用 AI 排程訊息才需要設定 Claude / OpenAI 金鑰，沒設定不影響其他功能。

### 從舊版（v2.x / App 1.2.x）升級

v3.0 是**破壞性升級**：

- 資料庫會在啟動時自動遷移：既有使用者全部成為「預設 Bot」的好友，Rich Menu、訊息、排程與 Webhook 日誌都歸到預設 Bot 底下。**升級前請先備份 `localbot.db`。**
- `APP_SECRET` 已移除（`.env` 裡的 `LOCALBOT_APP_SECRET` 可以刪掉）。舊版 App（1.2.x）無法連線，請安裝新版 App。
- 舊使用者沒有專屬金鑰：在新版 App 用邀請碼重新加入「預設 Bot」即可領到金鑰（userId 不變，原本的好友關係與歷史訊息保留）。請先到後台為預設 Bot 產生邀請碼。
- Bot 程式（`line-bot-sdk` 風格）不用改：原本的 `CHANNEL_SECRET` / `CHANNEL_ACCESS_TOKEN` 就是預設 Bot 的金鑰。Webhook 的 `destination` 現在是 Bot 的 ID（預設 Bot 為 `default`）。

## ⚙️ 設定（環境變數）

| 變數 | 預設值 | 說明 |
|---|---|---|
| `LOCALBOT_SERVER_URL` | `http://localhost:5003` | 平台對外網址（用來產生媒體檔 URL） |
| `LOCALBOT_PORT` | `5003` | app.py 監聽埠 |
| `LOCALBOT_BOT_WEBHOOK_URL` | `http://localhost:9000/callback` | 預設 Bot 的 Webhook 位址（只在第一次啟動建立預設 Bot 時使用） |
| `LOCALBOT_CHANNEL_SECRET` / `_ACCESS_TOKEN` | 自動產生 | 預設 Bot 的金鑰（同上，只在第一次啟動時使用） |
| `LOCALBOT_ADMIN_PASSWORD` | 自動產生 | 後台管理密碼（設了就不能在後台修改，要改環境變數） |
| `LOCALBOT_ADMIN_ENABLED` | `true` | 設為 `false` 則不提供 `/admin` |
| `LOCALBOT_ADMIN_SESSION_HOURS` | `8` | 後台登入有效時間 |
| `LOCALBOT_WEBHOOK_RETRY_DELAYS` | `10,60,300,1800` | Webhook 失敗後每次重試前等待的秒數（逗號分隔，最多 10 次）；留空＝不自動重試 |
| `LOCALBOT_WEBHOOK_TIMEOUT` | `15` | 轉送給 Bot 的逾時秒數 |
| `LOCALBOT_LOG_RETENTION_DAYS` | `30` | Webhook 日誌與排程執行紀錄保留天數 |
| `LOCALBOT_SCHEDULE_GRACE_MINUTES` | `60` | 排程錯過多久內仍會補送，超過就略過 |
| `LOCALBOT_WORKERS_ENABLED` | `true` | 設為 `false` 則不啟動背景工作（不重試、不跑排程） |
| `LOCALBOT_ANTHROPIC_API_KEY` | （空） | AI 排程訊息用的 Claude 金鑰（也接受 `ANTHROPIC_API_KEY`；或在後台「設定 → AI 金鑰」輸入） |
| `LOCALBOT_OPENAI_API_KEY` | （空） | AI 排程訊息用的 OpenAI 金鑰（也接受 `OPENAI_API_KEY`） |
| `LOCALBOT_DEBUG` | `false` | 只在本機開發時開啟 |
| `LOCALBOT_MAX_UPLOAD_MB` | `20` | 上傳檔案大小上限 |
| `LOCALBOT_CORS_ORIGINS` | `*` | Socket.IO 允許來源，逗號分隔 |

## 🧪 測試

```bash
# 伺服器（約 225 項，不會連到外部服務；AI 呼叫都以假回應測試）
cd server
python -m pytest -q tests

# App
cd flutter_app/localbot_app
flutter analyze
flutter test
```

GitHub Actions 會在每次推送時自動執行伺服器測試，並可手動觸發 iOS 編譯（未簽章）。

## 🔐 安全性說明

- 金鑰檔 `.localbot_secrets.json`、資料庫、上傳媒體都已列入 `.gitignore`，請勿上傳。
- 邀請碼等同「加入許可」：只分享給信任的人，並設定次數與期限；外洩時到後台撤銷即可。每支手機的金鑰只存在那支手機，伺服器只存雜湊，可以單獨撤銷，不影響其他人。
- 邀請碼輸入有失敗次數限制（防暴力猜測）。
- 正式環境請保持 `LOCALBOT_DEBUG=false`，並透過 HTTPS 對外。
- AI 金鑰只存在 `.localbot_secrets.json`（或環境變數），後台只顯示末四碼；請勿把它貼進 Issue 或程式碼。
- 發現安全問題請依 [SECURITY.md](SECURITY.md) 回報，不要公開漏洞細節。

## 🗺 Roadmap

- [x] line-bot-sdk v3 寫法、broadcast / multicast / narrowcast
- [x] Quick Reply、輸入中動畫
- [x] 影片 / 檔案 / Imagemap 訊息
- [x] follow / unfollow 事件
- [x] Flex Message 常用元件與屬性
- [x] Rich Menu
- [x] 內建網頁管理後台
- [x] 排程推播、Webhook 重試與日誌
- [x] 多 Bot、邀請碼 / QR Code 加入、每支手機獨立金鑰
- [x] Bot 頭像、引用回覆、快速送出、AI 產生的排程訊息
- [ ] 群組 / 多人聊天室
- [ ] Docker 一鍵部署
- [ ] Web 版用戶端

歡迎 PR 與 Issue！請先閱讀 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 📄 授權與聲明

本專案採用 [MIT License](LICENSE)。

LocalBot 是獨立的開源專案，與 LINE Corporation / LY Corporation 無任何關係。
「LINE」為其所有者之商標；本專案僅相容其公開的 Messaging API 介面設計，
不使用、也不連線至 LINE 的任何服務。
