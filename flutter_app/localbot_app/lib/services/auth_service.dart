import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import '../config.dart';
import '../models/bot_info.dart';

/// 加入 Bot（/join）的結果。
class JoinResult {
  final bool ok;
  final String message;
  final BotInfo? bot;

  /// 這次是否領到新的金鑰（第一次加入，或金鑰被撤銷後重新加入）
  final bool newKey;

  /// 伺服器網址和原本不同（原本的金鑰與本機紀錄已清除）
  final bool serverChanged;

  const JoinResult.success(this.bot, {this.newKey = false, this.serverChanged = false})
      : ok = true,
        message = '';

  const JoinResult.failure(this.message)
      : ok = false,
        bot = null,
        newKey = false,
        serverChanged = false;
}

enum MeStatus { ok, unauthorized, offline }

class MeResult {
  final MeStatus status;
  final List<BotInfo> bots;
  const MeResult(this.status, [this.bots = const []]);
}

/// 管理這支手機的身分：userId、伺服器網址、專屬金鑰，以及已加入的 Bot 清單（快取）。
///
/// 金鑰由伺服器在「第一次用邀請碼加入」時發給這支手機，伺服器只存雜湊。
/// 管理員可以在後台單獨撤銷；撤銷後 /me 會回 401，App 會要求用新的邀請碼重新加入。
class AuthService {
  static final AuthService _instance = AuthService._internal();
  factory AuthService() => _instance;
  AuthService._internal();

  late SharedPreferences _prefs;
  String _userId = '';
  String _displayName = 'User';
  String _serverUrl = AppConfig.defaultServerUrl;
  String _token = '';
  List<BotInfo> _bots = [];
  bool _keyRevoked = false;

  String get userId => _userId;
  String get displayName => _displayName;
  String get serverUrl => _serverUrl;
  List<BotInfo> get bots => List.unmodifiable(_bots);

  /// 是否持有金鑰（已經用邀請碼加入過）
  bool get hasKey => _token.isNotEmpty;

  /// 伺服器已不認得這把金鑰（被撤銷或使用者被刪除）
  bool get keyRevoked => _keyRevoked;

  String get baseUrl => _serverUrl.replaceAll(RegExp(r'/+$'), '');

  Map<String, String> get authHeaders => {'X-LocalBot-Token': _token};

  BotInfo? botById(String botId) {
    for (final b in _bots) {
      if (b.botId == botId) return b;
    }
    return null;
  }

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();

    _userId = _prefs.getString(AppConfig.keyUserId) ?? '';
    if (_userId.isEmpty) {
      _userId = const Uuid().v4();
      await _prefs.setString(AppConfig.keyUserId, _userId);
    }
    _displayName = _prefs.getString(AppConfig.keyDisplayName) ?? 'User';
    _serverUrl = _prefs.getString(AppConfig.keyServerUrl) ?? AppConfig.defaultServerUrl;
    _token = _prefs.getString(AppConfig.keyUserToken) ?? '';
    _bots = _readCachedBots();
  }

  List<BotInfo> _readCachedBots() {
    final raw = _prefs.getString(AppConfig.keyBots);
    if (raw == null || raw.isEmpty) return [];
    try {
      final data = jsonDecode(raw);
      if (data is List) {
        return data.whereType<Map>().map(BotInfo.fromJson).where((b) => b.botId.isNotEmpty).toList();
      }
    } catch (_) {}
    return [];
  }

  Future<void> _saveBots(List<BotInfo> bots) async {
    _bots = bots;
    await _prefs.setString(AppConfig.keyBots, jsonEncode(bots.map((b) => b.toJson()).toList()));
  }

  /// 把使用者輸入的伺服器網址整理成 https://host[:port]。無效時回傳 null。
  static String? normalizeServerUrl(String input) {
    final trimmed = input.trim().replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.tryParse(trimmed);
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty) return null;
    return trimmed;
  }

  // ---------------------------------------------------------------------------
  // 加入 Bot
  // ---------------------------------------------------------------------------
  Future<JoinResult> join({
    required String serverUrl,
    required String code,
    String? displayName,
  }) async {
    final url = normalizeServerUrl(serverUrl);
    if (url == null) return const JoinResult.failure('伺服器網址需以 https:// 開頭');

    var serverChanged = false;
    if (url != baseUrl && _token.isNotEmpty) {
      // 換了一台伺服器：舊金鑰與 Bot 清單都不能再用
      serverChanged = true;
      await _clearKey();
    }
    final name = (displayName ?? _displayName).trim();
    try {
      final response = await http
          .post(
            Uri.parse('$url/join'),
            headers: {'Content-Type': 'application/json', if (_token.isNotEmpty) ..._tokenHeader()},
            body: jsonEncode({
              'userId': _userId,
              'displayName': name.isEmpty ? 'User' : name,
              'code': code,
            }),
          )
          .timeout(const Duration(seconds: 12));

      Map<dynamic, dynamic> data = {};
      try {
        final decoded = jsonDecode(utf8.decode(response.bodyBytes));
        if (decoded is Map) data = decoded;
      } catch (_) {}

      if (response.statusCode != 200 || data['status'] != 'success' || data['bot'] is! Map) {
        final msg = data['message']?.toString();
        return JoinResult.failure(msg != null && msg.isNotEmpty ? msg : '加入失敗（HTTP ${response.statusCode}）');
      }

      final bot = BotInfo.fromJson(data['bot'] as Map).copyWith(blocked: data['blocked'] == true);
      final issued = data['token']?.toString() ?? '';
      _serverUrl = url;
      await _prefs.setString(AppConfig.keyServerUrl, url);
      if (issued.isNotEmpty) {
        _token = issued;
        await _prefs.setString(AppConfig.keyUserToken, issued);
      }
      _keyRevoked = false;
      if (name.isNotEmpty) {
        _displayName = name;
        await _prefs.setString(AppConfig.keyDisplayName, name);
      }
      final others = _bots.where((b) => b.botId != bot.botId).toList();
      await _saveBots([bot, ...others]);
      return JoinResult.success(bot, newKey: issued.isNotEmpty, serverChanged: serverChanged);
    } catch (_) {
      return const JoinResult.failure('無法連線到伺服器，請確認網址與網路');
    }
  }

  Map<String, String> _tokenHeader() => {'X-LocalBot-Token': _token};

  // ---------------------------------------------------------------------------
  // 同步我的 Bot 清單
  // ---------------------------------------------------------------------------
  Future<MeResult> fetchMe() async {
    if (_token.isEmpty) return const MeResult(MeStatus.unauthorized);
    try {
      final response = await http
          .get(
            Uri.parse('$baseUrl/me?userId=${Uri.encodeQueryComponent(_userId)}'),
            headers: authHeaders,
          )
          .timeout(const Duration(seconds: 8));
      if (response.statusCode == 401) {
        _keyRevoked = true;
        return const MeResult(MeStatus.unauthorized);
      }
      if (response.statusCode != 200) return const MeResult(MeStatus.offline);
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (data is! Map) return const MeResult(MeStatus.offline);
      _keyRevoked = false;
      final list = data['bots'] is List ? data['bots'] as List : const [];
      final bots = list.whereType<Map>().map(BotInfo.fromJson).where((b) => b.botId.isNotEmpty).toList();
      await _saveBots(bots);
      return MeResult(MeStatus.ok, bots);
    } catch (_) {
      return const MeResult(MeStatus.offline);
    }
  }

  // ---------------------------------------------------------------------------
  // 個別 Bot 操作
  // ---------------------------------------------------------------------------

  /// 封鎖或解除封鎖某個 Bot。成功時回傳 true。
  Future<bool> setBlocked(String botId, bool blocked) async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl/block'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: jsonEncode({'userId': _userId, 'botId': botId, 'blocked': blocked}),
          )
          .timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) return false;
      await _saveBots([
        for (final b in _bots) b.botId == botId ? b.copyWith(blocked: blocked) : b,
      ]);
      return true;
    } catch (_) {
      return false;
    }
  }

  /// 刪除好友：伺服器會清除這個 Bot 與我之間的所有紀錄。成功時回傳 true。
  Future<bool> leave(String botId) async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl/leave'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: jsonEncode({'userId': _userId, 'botId': botId}),
          )
          .timeout(const Duration(seconds: 8));
      // 404 = 伺服器那邊已經不是好友了，視同成功
      if (response.statusCode != 200 && response.statusCode != 404) return false;
      await _saveBots(_bots.where((b) => b.botId != botId).toList());
      return true;
    } catch (_) {
      return false;
    }
  }

  /// 修改顯示名稱（所有 Bot 看到的是同一個名稱）。伺服器同步失敗時仍會儲存在本機。
  Future<bool> updateDisplayName(String name) async {
    final trimmed = name.trim();
    if (trimmed.isEmpty) return false;
    _displayName = trimmed;
    await _prefs.setString(AppConfig.keyDisplayName, trimmed);
    if (_token.isEmpty) return true;
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl/profile'),
            headers: {'Content-Type': 'application/json', ...authHeaders},
            body: jsonEncode({'userId': _userId, 'displayName': trimmed}),
          )
          .timeout(const Duration(seconds: 8));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// 只更換伺服器網址（例如網域改了），金鑰與 Bot 清單保留。
  /// 如果其實是另一台伺服器，之後同步時會被判定為金鑰無效，要用新邀請碼重新加入。
  Future<bool> updateServerUrl(String input) async {
    final url = normalizeServerUrl(input);
    if (url == null) return false;
    _serverUrl = url;
    await _prefs.setString(AppConfig.keyServerUrl, url);
    return true;
  }

  // ---------------------------------------------------------------------------
  // 重設
  // ---------------------------------------------------------------------------
  Future<void> _clearKey() async {
    _token = '';
    _keyRevoked = false;
    await _prefs.remove(AppConfig.keyUserToken);
    await _saveBots([]);
  }

  /// 清除金鑰與 Bot 清單，並換一個新的 userId（等同全新安裝）。
  /// 用在「金鑰被撤銷」或「想重新開始」時；需要新的邀請碼才能再加入。
  Future<void> resetIdentity() async {
    await _clearKey();
    _userId = const Uuid().v4();
    await _prefs.setString(AppConfig.keyUserId, _userId);
    await _prefs.remove(AppConfig.keyLastBot);
    await _prefs.remove(AppConfig.keyUnread);
  }

  /// 金鑰被撤銷後，保留 userId 與伺服器網址，只清掉失效的金鑰，讓使用者用新的邀請碼重新領取。
  Future<void> dropRevokedKey() async {
    await _clearKey();
  }
}
