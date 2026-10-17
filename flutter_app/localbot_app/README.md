# LocalBot App

LocalBot 的 Flutter 手機 App（版本見 `pubspec.yaml`，目前 1.4.0+6）。平台與整體說明請看[根目錄 README](../../README.md)。

## 功能

文字、圖片、影片、檔案、語音、位置、貼圖；Template / Flex / Imagemap / Quick Reply / Rich Menu 的顯示與互動；
離線佇列與快速送出、引用回覆、長按選單（複製、刪除）、未讀分隔線、每個 Bot 的頭像、深色模式；
可加入多個 Bot（邀請碼或 QR Code），每支手機一把獨立金鑰。

## 開發

```bash
flutter pub get
flutter analyze
flutter test
flutter run --dart-define=LOCALBOT_SERVER_URL=https://your-domain.example.com
```

## 編譯

```bash
# Android APK
flutter build apk --release --dart-define=LOCALBOT_SERVER_URL=https://your-domain.example.com
# 輸出：build/app/outputs/flutter-apk/app-release.apk（請放到 GitHub Releases，不要提交進 repo）
```

iOS 可用 GitHub Actions 的 *iOS Build (unsigned)* 編譯未簽章版本；上架或安裝到實機需要自己的 Apple 開發者帳號簽章。

`LOCALBOT_SERVER_URL` 只是邀請流程的預設伺服器網址，使用者也可以在加入時手動輸入。
Android 目前使用 debug key 簽章，正式發佈前請建立自己的 keystore（`key.properties` 與 keystore 已被 `.gitignore` 排除）。
