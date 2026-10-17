import 'dart:async';
import 'dart:convert';
import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../config.dart';
import '../models/bot_info.dart';
import '../models/message.dart';
import 'auth_service.dart';
import 'database_service.dart';
import 'socket_service.dart';

enum HubStatus {
  /// 還沒有金鑰：需要用邀請碼加入
  needsJoin,

  /// 金鑰已被伺服器撤銷：需要新的邀請碼
  revoked,

  /// 正常
  ready,
}

/// 所有 Bot 共用的中樞：同步 Bot 清單、只開一條 Socket.IO 連線、
/// 把每個 Bot 收到的訊息存進本機資料庫並累計未讀數。
/// 聊天室畫面（ChatScreen）只負責顯示它開著的那個 Bot。
class ChatHub extends ChangeNotifier {
  static final ChatHub _instance = ChatHub._internal();
  factory ChatHub() => _instance;
  ChatHub._internal();

  final AuthService _auth = AuthService();
  final DatabaseService _db = DatabaseService();
  final SocketService _socket = SocketService();

  HubStatus _status = HubStatus.needsJoin;
  HubStatus get status => _status;

  final Map<String, int> _unread = {};
  final Map<String, ChatMessage> _last = {};

  /// 目前開著的聊天室（收到這個 Bot 的訊息不算未讀）
  String? openBotId;

  bool _started = false;
  bool _refreshing = false;
  _LifecycleWatcher? _lifecycle;
  DateTime? _pausedAt;
  DateTime _lastRefresh = DateTime.fromMillisecondsSinceEpoch(0);
  final List<StreamSubscription> _subs = [];

  /// 已存進本機資料庫、屬於某個 Bot 的新訊息（來自 Bot）
  final _messageController = StreamController<ChatMessage>.broadcast();
  Stream<ChatMessage> get onMessage => _messageController.stream;

  /// 伺服器通知送不到 Bot 的訊息（已在本機標成 failed）：(botId, 訊息 id 清單)
  final _deliveryFailedController = StreamController<(String, List<String>)>.broadcast();
  Stream<(String, List<String>)> get onDeliveryFailed => _deliveryFailedController.stream;

  /// 最近被通知失敗的訊息 id。通知可能比 HTTP 回應更早到（聊天室還沒把訊息存好），
  /// 聊天室存檔時用 [takeFailed] 補標。
  final Set<String> _recentlyFailed = {};

  List<BotInfo> get bots => _auth.bots;
  int unreadFor(String botId) => _unread[botId] ?? 0;
  int get totalUnread => _unread.values.fold(0, (a, b) => a + b);
  ChatMessage? lastMessageOf(String botId) => _last[botId];

  Stream<(String, int)> get onTyping => _socket.onLoading;
  Stream<String> get onRichMenuChanged => _socket.onRichMenuChanged;
  Stream<SocketConnectionState> get onConnectionState => _socket.onStateChanged;
  SocketConnectionState get connectionState => _socket.connectionState;

  // ---------------------------------------------------------------------------
  // 啟動 / 停止
  // ---------------------------------------------------------------------------

  /// App 啟動（或加入成功）後呼叫。沒有金鑰時只更新狀態，不連線。
  Future<void> start() async {
    if (!_auth.hasKey) {
      _setStatus(HubStatus.needsJoin);
      return;
    }
    _setStatus(_auth.keyRevoked ? HubStatus.revoked : HubStatus.ready);
    await _loadUnread();
    await _loadPreviews();
    if (_lifecycle == null) {
      _lifecycle = _LifecycleWatcher(_onLifecycle);
      WidgetsBinding.instance.addObserver(_lifecycle!);
    }
    if (!_started) {
      _started = true;
      _subs.add(_socket.onMessageReceived.listen(_onSocketMessage));
      _subs.add(_socket.onDeliveryFailed.listen(_onDeliveryFailed));
      _subs.add(_socket.onConnectError.listen((_) => refresh(minInterval: const Duration(seconds: 30))));
      _subs.add(_socket.onStateChanged.listen((state) {
        if (state == SocketConnectionState.connected) {
          refresh(minInterval: const Duration(seconds: 30));
        }
      }));
    }
    _socket.connect();
    unawaited(refresh());
  }

  /// 停止連線並回到「需要加入」狀態（重設身分、金鑰被撤銷時使用）。
  Future<void> stop({HubStatus status = HubStatus.needsJoin}) async {
    _socket.disconnect();
    for (final s in _subs) {
      await s.cancel();
    }
    _subs.clear();
    _started = false;
    _setStatus(status);
  }

  /// App 回到前景：連線斷了就重連；在背景待超過 30 秒，系統可能已經默默切斷連線，直接重連。
  void _onLifecycle(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) {
      _pausedAt ??= DateTime.now();
      return;
    }
    if (state != AppLifecycleState.resumed) return;
    final away = _pausedAt == null ? Duration.zero : DateTime.now().difference(_pausedAt!);
    _pausedAt = null;
    if (!_started || _status != HubStatus.ready) return;
    _socket.ensureConnected(force: away > const Duration(seconds: 30));
    unawaited(refresh(minInterval: const Duration(seconds: 30)));
  }

  void _setStatus(HubStatus status) {
    if (_status == status) return;
    _status = status;
    notifyListeners();
  }

  // ---------------------------------------------------------------------------
  // Bot 清單同步
  // ---------------------------------------------------------------------------

  /// 向伺服器同步 Bot 清單；金鑰被撤銷時切到 [HubStatus.revoked]。
  Future<void> refresh({Duration minInterval = Duration.zero}) async {
    if (_refreshing || !_auth.hasKey) return;
    if (DateTime.now().difference(_lastRefresh) < minInterval) return;
    _refreshing = true;
    try {
      final before = _auth.bots.map((b) => b.botId).toSet();
      final result = await _auth.fetchMe();
      _lastRefresh = DateTime.now();
      switch (result.status) {
        case MeStatus.unauthorized:
          _socket.disconnect();
          _setStatus(HubStatus.revoked);
        case MeStatus.offline:
          break;
        case MeStatus.ok:
          _setStatus(HubStatus.ready);
          final now = result.bots.map((b) => b.botId).toSet();
          for (final gone in before.difference(now)) {
            // Bot 被管理員刪除或停用：本機紀錄一併清掉
            await _db.clear(botId: gone);
            _unread.remove(gone);
            _last.remove(gone);
          }
          await _saveUnread();
          await _loadPreviews();
          notifyListeners();
      }
    } finally {
      _refreshing = false;
    }
  }

  // ---------------------------------------------------------------------------
  // 訊息
  // ---------------------------------------------------------------------------
  Future<void> _onSocketMessage(ChatMessage message) async {
    if (message.botId.isEmpty) return;
    await _db.saveMessage(message);
    _last[message.botId] = message;
    if (openBotId != message.botId) {
      _unread[message.botId] = unreadFor(message.botId) + 1;
      await _saveUnread();
    }
    _messageController.add(message);
    notifyListeners();
  }

  Future<void> _onDeliveryFailed((String, List<String>) event) async {
    final (botId, ids) = event;
    if (botId.isEmpty || ids.isEmpty) return;
    for (final id in ids) {
      _recentlyFailed.add(id);
      await _db.updateMessageStatus(botId, id, 'failed');
    }
    while (_recentlyFailed.length > 50) {
      _recentlyFailed.remove(_recentlyFailed.first);
    }
    _deliveryFailedController.add(event);
  }

  /// 這則訊息剛剛被伺服器通知送不到嗎？（查過就移除）
  bool takeFailed(String messageId) => _recentlyFailed.remove(messageId);

  /// 聊天室裡自己送出 / 同步到的訊息也要更新清單上的預覽
  void noteLocalMessage(ChatMessage message) {
    final current = _last[message.botId];
    if (current == null || !message.timestamp.isBefore(current.timestamp)) {
      _last[message.botId] = message;
      notifyListeners();
    }
  }

  Future<void> markRead(String botId) async {
    if ((_unread[botId] ?? 0) == 0) return;
    _unread.remove(botId);
    await _saveUnread();
    notifyListeners();
  }

  /// Bot 封鎖狀態、被刪除等本機改動後，重新讀取清單與預覽
  Future<void> reload() async {
    await _loadPreviews();
    notifyListeners();
  }

  Future<void> removeBotLocally(String botId) async {
    await _db.clear(botId: botId);
    _unread.remove(botId);
    _last.remove(botId);
    await _saveUnread();
    notifyListeners();
  }

  /// 清掉所有本機資料（換伺服器、重設身分）
  Future<void> wipeLocalData() async {
    await _db.clear();
    _unread.clear();
    _last.clear();
    await _saveUnread();
    notifyListeners();
  }

  // ---------------------------------------------------------------------------
  // 本機快取
  // ---------------------------------------------------------------------------
  Future<void> _loadPreviews() async {
    for (final bot in _auth.bots) {
      final last = await _db.getLastMessage(bot.botId);
      if (last != null) _last[bot.botId] = last;
    }
  }

  Future<void> _loadUnread() async {
    final prefs = await SharedPreferences.getInstance();
    _unread.clear();
    final raw = prefs.getString(AppConfig.keyUnread);
    if (raw == null || raw.isEmpty) return;
    try {
      final data = jsonDecode(raw);
      if (data is Map) {
        data.forEach((k, v) {
          if (v is num && v > 0) _unread[k.toString()] = v.toInt();
        });
      }
    } catch (_) {}
  }

  Future<void> _saveUnread() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(AppConfig.keyUnread, jsonEncode(_unread));
  }
}


class _LifecycleWatcher extends WidgetsBindingObserver {
  _LifecycleWatcher(this.onChange);
  final void Function(AppLifecycleState) onChange;

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) => onChange(state);
}
