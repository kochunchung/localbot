# 更新紀錄

版本格式：平台（server）與 App 各自編號。日期為發佈日。

## 平台 v3.1.0 ／ App v1.4.0（2026-10）

### 新功能
- **快速送出**：App 送訊息帶 `X-LocalBot-Async: 1`，平台存好就立刻回應，再於背景依序轉送給 Bot；最後確定送不到時，以 Socket.IO `delivery_failed` 事件通知 App 標示失敗。舊版 App 行為不變。
- **每個 Bot 的頭像**：後台上傳（PNG / JPEG / WebP，1 MB 內），App 的 Bot 清單與聊天室顯示；公開網址 `/avatars/<檔名>`。
- **引用回覆**：App 長按訊息可回覆；Bot 在文字訊息事件收到 `quotedMessageId`（`localbot` 與 `localbot.v3` 皆支援）。
- **AI 產生的排程訊息**：排程內容可選「AI 產生」，每次執行時由 Claude 或 OpenAI 依提示詞（可上網搜尋）寫好內容再送出；提示詞支援 `{today}` `{yesterday}` `{weekday}` `{now}`；後台可輸入金鑰與「試產生一次」。
- **聊天介面更接近 LINE**：連續訊息群組、日期分隔、訊息時間、「以下為未讀訊息」分隔線、跳到最新按鈕、輸入中動畫、檔案與媒體泡泡重新設計。

### 其他
- 新增環境變數 `LOCALBOT_ANTHROPIC_API_KEY`、`LOCALBOT_OPENAI_API_KEY`（皆為選用）。
- 資料庫自動新增 `bots.avatar` 欄位，不需手動遷移。
- 測試：伺服器約 225 項、App 18 項。

## 平台 v3.0.0 ／ App v1.3.x

> 破壞性升級，細節見 README「升級」一節。

- **多 Bot**：一台平台服務多個 Bot，各自有 Webhook、金鑰、好友與 Rich Menu。
- **邀請碼 / QR Code 加入**，每支手機獨立金鑰（伺服器只存雜湊），可在後台單獨撤銷；移除共用的 `APP_SECRET`。
- 排程推播（單次／每日／每週／每月）、Webhook 自動重試與日誌、後台重送。
- Webhook 事件 `destination` 改為 Bot 的 ID（預設 Bot 為 `default`）。

## 平台 v2.x ／ App v1.2.x

- 內建網頁管理後台（`/admin`）。
- Rich Menu（預設、個別使用者、別名切換）、follow / unfollow 事件。
- Flex Message、Imagemap、影片與檔案訊息、Quick Reply、輸入中動畫。
- line-bot-sdk v3 寫法（`localbot.v3`）、broadcast / multicast / narrowcast。

## v1.0 — 首次公開

- 平台伺服器、Flutter App、`localbot` 相容 SDK，以及基本安全強化（Webhook 簽名、Bearer Token、上傳檔案限制）。
