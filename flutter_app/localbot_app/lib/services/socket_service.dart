import 'dart:async';
import 'package:socket_io_client/socket_io_client.dart' as io;
import 'auth_service.dart';
import '../models/message.dart';

enum SocketConnectionState {
  connecting,
  connected,
  disconnected,
}

/// Service managing the Socket.IO real-time connection to the server.
class SocketService {
  static final SocketService _instance = SocketService._internal();
  factory SocketService() => _instance;
  SocketService._internal();

  final AuthService _auth = AuthService();
  io.Socket? _socket;

  SocketConnectionState _connectionState = SocketConnectionState.disconnected;
  SocketConnectionState get connectionState => _connectionState;

  final _messageController = StreamController<ChatMessage>.broadcast();
  Stream<ChatMessage> get onMessageReceived => _messageController.stream;

  final _stateController = StreamController<SocketConnectionState>.broadcast();
  Stream<SocketConnectionState> get onStateChanged => _stateController.stream;

  /// Bot 呼叫 show_loading_animation 時送出：(botId, 顯示秒數)。
  final _loadingController = StreamController<(String, int)>.broadcast();
  Stream<(String, int)> get onLoading => _loadingController.stream;

  /// Bot 變更了這位使用者的 Rich Menu，App 需要重新載入；內容是 botId（空字串 = 全部 Bot）。
  final _richMenuController = StreamController<String>.broadcast();
  Stream<String> get onRichMenuChanged => _richMenuController.stream;

  /// 伺服器在背景轉送給 Bot 失敗（Bot 回錯誤、不再重試）：(botId, 訊息 id 清單)。
  final _deliveryFailedController = StreamController<(String, List<String>)>.broadcast();
  Stream<(String, List<String>)> get onDeliveryFailed => _deliveryFailedController.stream;

  /// 連線被伺服器拒絕（金鑰無效或被撤銷）時送出，讓上層去確認金鑰狀態。
  final _rejectedController = StreamController<void>.broadcast();
  Stream<void> get onConnectError => _rejectedController.stream;

  /// 目前這條連線是用哪個身分（伺服器 + userId + 金鑰）建立的
  String _identity = '';

  String get _currentIdentity =>
      '${_auth.baseUrl}|${_auth.userId}|${_auth.authHeaders['X-LocalBot-Token'] ?? ''}';

  void connect() {
    if (_socket != null) {
      _socket!.dispose();
      _socket = null;
    }

    _updateState(SocketConnectionState.connecting);

    final serverUrl = _auth.baseUrl;
    final userId = _auth.userId;
    _identity = _currentIdentity;

    // enableForceNew：每次都建立全新的連線。socket_io_client 預設會依網址快取並沿用
    // 舊的連線（連同舊的 userId / 金鑰），換身分或重新加入後會變成「伺服器以為你離線」。
    final options = io.OptionBuilder()
        .setTransports(['websocket', 'polling'])
        .enableForceNew()
        .enableAutoConnect()
        .enableReconnection()
        .setReconnectionDelay(2000)
        .setAuth({'userId': userId, 'token': _auth.authHeaders['X-LocalBot-Token'] ?? ''})
        .setQuery({'userId': userId})
        .build();

    _socket = io.io(serverUrl, options);

    _socket!.onConnect((_) {
      _updateState(SocketConnectionState.connected);
      // 離線期間選單可能被 Bot 改過，重新連線時順便重新載入
      _richMenuController.add('');
    });

    _socket!.onDisconnect((_) {
      _updateState(SocketConnectionState.disconnected);
    });

    _socket!.onConnectError((err) {
      _updateState(SocketConnectionState.disconnected);
      _rejectedController.add(null);
    });

    _socket!.onError((err) {
      _updateState(SocketConnectionState.disconnected);
    });

    // Listen to messages pushed from bot
    _socket!.on('bot_message', (data) {
      if (data is Map<String, dynamic>) {
        final message = ChatMessage.fromSocketPayload(data);
        _messageController.add(message);
      } else if (data is Map) {
        final message = ChatMessage.fromSocketPayload(Map<String, dynamic>.from(data));
        _messageController.add(message);
      }
    });

    // Bot 要求顯示「輸入中」動畫
    _socket!.on('loading', (data) {
      var seconds = 20;
      var botId = '';
      if (data is Map) {
        final raw = data['loadingSeconds'];
        if (raw is num) seconds = raw.toInt();
        botId = (data['botId'] ?? '').toString();
      }
      _loadingController.add((botId, seconds.clamp(5, 60)));
    });

    _socket!.on('richmenu_changed', (data) {
      final botId = data is Map ? (data['botId'] ?? '').toString() : '';
      _richMenuController.add(botId);
    });

    _socket!.on('delivery_failed', (data) {
      if (data is! Map) return;
      final botId = (data['botId'] ?? '').toString();
      final raw = data['messageIds'];
      final ids = raw is List ? raw.map((e) => e.toString()).toList() : <String>[];
      _deliveryFailedController.add((botId, ids));
    });
  }

  /// 沒連上、或身分（伺服器 / userId / 金鑰）已經換了，就重新連線；已正常連線則什麼都不做。
  /// [force] 為 true 時一律重連（例如 App 在背景待太久，連線可能已經失效）。
  void ensureConnected({bool force = false}) {
    if (!_auth.hasKey) return;
    final stale = _socket == null ||
        _identity != _currentIdentity ||
        _connectionState == SocketConnectionState.disconnected;
    if (force || stale) connect();
  }

  void disconnect() {
    if (_socket != null) {
      _socket!.disconnect();
      _socket!.dispose();
      _socket = null;
    }
    _identity = '';
    _updateState(SocketConnectionState.disconnected);
  }

  void _updateState(SocketConnectionState newState) {
    if (_connectionState != newState) {
      _connectionState = newState;
      _stateController.add(_connectionState);
    }
  }

  void dispose() {
    disconnect();
    _messageController.close();
    _stateController.close();
    _loadingController.close();
    _richMenuController.close();
    _deliveryFailedController.close();
    _rejectedController.close();
  }
}
