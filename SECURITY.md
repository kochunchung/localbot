# 安全性政策

## 回報漏洞

請**不要**在公開 Issue 貼出漏洞細節或任何金鑰。請透過 GitHub 的 *Security → Report a vulnerability*（私人安全通報）回報；
若該功能未開啟，可先開一個只寫「想回報安全問題」的 Issue，作者會再與你私下聯絡。

## 支援的版本

只維護最新版（平台 3.x、App 1.x）。

## 設計重點

- Webhook：HMAC-SHA256 簽名（`X-Line-Signature`），沒有簽名一律拒絕。
- Bot → 平台：每個 Bot 獨立的 `Authorization: Bearer <CHANNEL_ACCESS_TOKEN>`。
- 手機 → 平台：每支手機獨立金鑰（`lbu_…`），伺服器只存 SHA-256 雜湊，可單獨撤銷。
- 管理後台：HttpOnly + SameSite=Strict Cookie、CSRF token、嚴格 CSP、登入失敗次數限制；顯示 / 重新產生金鑰需再輸入密碼。
- 上傳：ID 與副檔名白名單、大小上限（預設 20 MB）；頭像另限 1 MB 並檢查檔案內容。
- AI 金鑰：只存在環境變數或 `.localbot_secrets.json`，後台只顯示末四碼。

## 部署建議

- 只透過 HTTPS 對外（App 預設不允許明文 HTTP）；`LOCALBOT_DEBUG` 保持 `false`。
- 後台對外時使用夠長的密碼，最好再加一層反向代理保護（Nginx / Cloudflare Access）。
- 定期備份 `localbot.db` 與 `.localbot_secrets.json`，並限制這兩個檔案的讀取權限。
