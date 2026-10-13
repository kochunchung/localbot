/// Configuration for LocalBot App.
class AppConfig {
  /// Default Server URL — 請改成你自己的平台網址，或在 App 設定頁輸入。
  /// 可在 build 時指定：flutter build apk --dart-define=LOCALBOT_SERVER_URL=https://your-domain
  static const String defaultServerUrl = String.fromEnvironment(
    'LOCALBOT_SERVER_URL',
    defaultValue: 'https://your-domain.example.com',
  );

  /// App Secret（對應伺服器的 LOCALBOT_APP_SECRET）。
  /// 預設留空，使用者在設定頁輸入；不要把真正的金鑰寫死在原始碼裡。
  static const String defaultChannelSecret = String.fromEnvironment(
    'LOCALBOT_APP_SECRET',
    defaultValue: '',
  );

  /// OpenStreetMap Nominatim 要求可識別的 User-Agent
  static const String nominatimUserAgent = 'LocalBotApp/1.0 (self-hosted LocalBot client)';

  /// Storage keys
  static const String keyServerUrl = 'localbot_server_url';
  static const String keyChannelSecret = 'localbot_channel_secret';
  static const String keyUserId = 'localbot_user_id';
  static const String keyDisplayName = 'localbot_display_name';
  static const String keyBotName = 'localbot_bot_name';

  /// 聊天室標題預設顯示的 Bot 名稱（可在設定頁修改）
  static const String defaultBotName = 'LocalBot 助理';

  /// App 版本（顯示於設定頁）
  static const String appVersion = '1.1.0';
}
