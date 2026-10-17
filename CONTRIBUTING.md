# 參與貢獻

歡迎 Issue 與 Pull Request。

## 開發環境

```bash
# 伺服器（Python 3.10+）
cd server
python -m venv venv && venv\Scripts\activate      # macOS / Linux：source venv/bin/activate
pip install -r requirements.txt
python app.py
python -m pytest -q tests                         # 送出 PR 前請確認全部通過

# App（Flutter 3.x）
cd flutter_app/localbot_app
flutter pub get
flutter analyze                                   # 需為「No issues found」
flutter test
```

## 原則

- **相容性優先**：`server/localbot/` 對外的類別與方法名稱要與 `line-bot-sdk` 一致，不要為了方便改名。
- **有行為就要有測試**：新功能請在 `server/tests/` 或 `flutter_app/localbot_app/test/` 補測試；測試不可連到外部網路（AI、Webhook 都用假回應）。
- **管理後台**：維持單一檔案 `server/admin_ui/index.html`、不載入外部資源、不使用 `innerHTML`；`TestUiStatic` 會檢查。
- **資料庫**：只新增欄位 / 資料表（`_add_column`），啟動時自動遷移；不要做會讓舊資料失效的變更。
- **密碼與金鑰**：絕對不要提交 `.env`、`.localbot_secrets.json`、資料庫、個人 Bot 程式（如 `local_bot.py`）、APK。`.gitignore` 已排除，但請在 `git status` 再確認一次。
- 繁體中文與英文的 Issue / PR 都可以。

## 提交訊息

簡短說明做了什麼，例如 `feat: 排程支援 AI 產生訊息`、`fix: 檔案泡泡文字`。
