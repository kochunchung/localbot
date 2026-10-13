import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import '../config.dart';

/// Manages User Identity, Settings, and HMAC-SHA256 Signing.
class AuthService {
  static final AuthService _instance = AuthService._internal();
  factory AuthService() => _instance;
  AuthService._internal();

  late SharedPreferences _prefs;
  String _userId = '';
  String _displayName = 'User';
  String _botName = AppConfig.defaultBotName;
  String _serverUrl = AppConfig.defaultServerUrl;
  String _channelSecret = AppConfig.defaultChannelSecret;

  String get userId => _userId;
  String get displayName => _displayName;
  String get botName => _botName;
  String get serverUrl => _serverUrl;
  String get channelSecret => _channelSecret;

  /// Initialize and load saved credentials from local storage.
  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();

    _userId = _prefs.getString(AppConfig.keyUserId) ?? '';
    if (_userId.isEmpty) {
      _userId = const Uuid().v4();
      await _prefs.setString(AppConfig.keyUserId, _userId);
    }

    _displayName = _prefs.getString(AppConfig.keyDisplayName) ?? 'User';
    _botName = _prefs.getString(AppConfig.keyBotName) ?? AppConfig.defaultBotName;
    _serverUrl = _prefs.getString(AppConfig.keyServerUrl) ?? AppConfig.defaultServerUrl;
    _channelSecret = _prefs.getString(AppConfig.keyChannelSecret) ?? AppConfig.defaultChannelSecret;
  }

  /// Update server settings.
  Future<void> updateSettings({
    required String serverUrl,
    required String channelSecret,
    String? displayName,
    String? botName,
  }) async {
    _serverUrl = serverUrl.trim();
    _channelSecret = channelSecret.trim();
    if (displayName != null) {
      _displayName = displayName.trim();
      await _prefs.setString(AppConfig.keyDisplayName, _displayName);
    }
    if (botName != null) {
      final trimmed = botName.trim();
      _botName = trimmed.isEmpty ? AppConfig.defaultBotName : trimmed;
      await _prefs.setString(AppConfig.keyBotName, _botName);
    }
    await _prefs.setString(AppConfig.keyServerUrl, _serverUrl);
    await _prefs.setString(AppConfig.keyChannelSecret, _channelSecret);
  }

  /// Calculate HMAC-SHA256 signature for outgoing webhook payload.
  String signPayload(String body) {
    final key = utf8.encode(_channelSecret);
    final bytes = utf8.encode(body);
    final hmacSha256 = Hmac(sha256, key);
    final digest = hmacSha256.convert(bytes);
    return base64.encode(digest.bytes);
  }

  /// Per-user access token = HMAC(AppSecret, userId)。
  /// 伺服器用它驗證 /register、/upload、/history 與 Socket.IO 連線。
  String get userToken => signPayload(_userId);

  /// Register device with the LocalBot server.
  Future<bool> registerWithServer() async {
    try {
      final uri = Uri.parse('${_serverUrl.replaceAll(RegExp(r'/+$'), '')}/register');
      final response = await http.post(
        uri,
        headers: {
          'Content-Type': 'application/json',
          'X-LocalBot-Token': userToken,
        },
        body: jsonEncode({
          'userId': _userId,
          'displayName': _displayName,
        }),
      ).timeout(const Duration(seconds: 8));

      return response.statusCode == 200;
    } catch (e) {
      // Ignore offline registration errors; will work when connection is established
      return false;
    }
  }
}
