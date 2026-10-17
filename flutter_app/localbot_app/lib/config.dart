/// Configuration for LocalBot App.
class AppConfig {
  /// 預設的伺服器網址（可選）。邀請碼加入畫面會用它當預設值；
  /// 邀請連結 / QR Code 內本來就含有伺服器網址，通常不需要設定。
  /// 可在 build 時指定：flutter build apk --dart-define=LOCALBOT_SERVER_URL=https://your-domain
  static const String defaultServerUrl = String.fromEnvironment(
    'LOCALBOT_SERVER_URL',
    defaultValue: '',
  );

  /// OpenStreetMap Nominatim 要求可識別的 User-Agent
  static const String nominatimUserAgent = 'LocalBotApp/1.0 (self-hosted LocalBot client)';

  /// Storage keys
  static const String keyServerUrl = 'localbot_server_url';
  static const String keyUserToken = 'localbot_user_token';
  static const String keyUserId = 'localbot_user_id';
  static const String keyDisplayName = 'localbot_display_name';
  static const String keyBots = 'localbot_bots';
  static const String keyUnread = 'localbot_unread';
  static const String keyLastBot = 'localbot_last_bot';

  /// 邀請連結：localbot://join?server=<網址>&code=<邀請碼>
  static const String inviteScheme = 'localbot';
  static const String inviteHost = 'join';

  /// App 版本（顯示於設定頁）
  static const String appVersion = '1.3.0';
}
