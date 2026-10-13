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

  void connect() {
    if (_socket != null) {
      _socket!.dispose();
      _socket = null;
    }

    _updateState(SocketConnectionState.connecting);

    final serverUrl = _auth.serverUrl.replaceAll(RegExp(r'/+$'), '');
    final userId = _auth.userId;

    final options = io.OptionBuilder()
        .setTransports(['websocket', 'polling'])
        .enableAutoConnect()
        .enableReconnection()
        .setReconnectionDelay(2000)
        .setAuth({'userId': userId, 'token': _auth.userToken})
        .setQuery({'userId': userId})
        .build();

    _socket = io.io(serverUrl, options);

    _socket!.onConnect((_) {
      _updateState(SocketConnectionState.connected);
    });

    _socket!.onDisconnect((_) {
      _updateState(SocketConnectionState.disconnected);
    });

    _socket!.onConnectError((err) {
      _updateState(SocketConnectionState.disconnected);
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
  }

  void disconnect() {
    if (_socket != null) {
      _socket!.disconnect();
      _socket!.dispose();
      _socket = null;
    }
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
  }
}
