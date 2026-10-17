import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';
import 'auth_service.dart';
import 'socket_service.dart';
import '../models/message.dart';

/// Service for communicating with LocalBot Server via HTTP REST endpoints.
class ApiService {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  final AuthService _auth = AuthService();
  final Uuid _uuid = const Uuid();

  String get _baseUrl => _auth.baseUrl;

  /// Send a LINE-compatible Webhook event to /callback.
  /// destination 是要傳給哪個 Bot；以這支手機的金鑰（X-LocalBot-Token）驗證身分。
  Future<bool> _sendWebhookEvent(String botId, Map<String, dynamic> event) async {
    final payload = {
      'destination': botId,
      'events': [event],
    };

    final body = jsonEncode(payload);

    // Bot 的回覆是經由 Socket.IO 推回來的；送出前確認接收管道是通的，
    // 斷線的話先重連（伺服器會把離線期間的回覆在連上時補送）。
    SocketService().ensureConnected();

    try {
      final uri = Uri.parse('$_baseUrl/callback');
      final response = await http.post(
        uri,
        headers: {
          'Content-Type': 'application/json',
          // 快速送出：伺服器存好訊息就先回應，再在背景轉給 Bot；
          // 最後確定送不到時會用 Socket.IO 的 delivery_failed 事件通知（見 ChatHub）。
          'X-LocalBot-Async': '1',
          ..._auth.authHeaders,
        },
        body: body,
      ).timeout(const Duration(seconds: 10));

      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  /// Send a plain text message.
  ///
  /// [quotedMessageId]：長按「回覆」某則訊息時帶入（與 LINE 的 quotedMessageId 相同）。
  Future<ChatMessage?> sendTextMessage(String botId, String text, {String? quotedMessageId}) async {
    final msgId = 'msg_${_uuid.v4()}';
    final replyToken = 'reply_${_uuid.v4()}';
    final now = DateTime.now();

    final event = {
      'type': 'message',
      'replyToken': replyToken,
      'timestamp': now.millisecondsSinceEpoch,
      'source': {
        'type': 'user',
        'userId': _auth.userId,
      },
      'message': {
        'id': msgId,
        'type': 'text',
        'text': text,
        if (quotedMessageId != null) 'quotedMessageId': quotedMessageId,
      },
    };

    final success = await _sendWebhookEvent(botId, event);

    return ChatMessage(
      id: msgId,
      botId: botId,
      userId: _auth.userId,
      isUser: true,
      messageType: 'text',
      content: {
        'text': text,
        if (quotedMessageId != null) 'quotedMessageId': quotedMessageId,
      },
      timestamp: now,
      status: success ? 'sent' : 'failed',
    );
  }

  /// Send a Postback action event (when user clicks template or flex button).
  ///
  /// [params] 為日期時間選擇器的結果，例如 `{'date': '2026-10-13'}`。
  /// [displayText] 只在 App 端顯示，與 LINE 相同不會放進 postback 事件。
  Future<bool> sendPostback(
    String botId,
    String data, {
    String? displayText,
    Map<String, String>? params,
  }) async {
    final replyToken = 'reply_${_uuid.v4()}';
    final now = DateTime.now();

    final event = {
      'type': 'postback',
      'replyToken': replyToken,
      'timestamp': now.millisecondsSinceEpoch,
      'source': {
        'type': 'user',
        'userId': _auth.userId,
      },
      'postback': {
        'data': data,
        if (params != null && params.isNotEmpty) 'params': params,
      },
    };

    return await _sendWebhookEvent(botId, event);
  }

  /// Send a Sticker message.
  Future<ChatMessage?> sendSticker(String botId, String packageId, String stickerId) async {
    final msgId = 'msg_${_uuid.v4()}';
    final replyToken = 'reply_${_uuid.v4()}';
    final now = DateTime.now();

    final event = {
      'type': 'message',
      'replyToken': replyToken,
      'timestamp': now.millisecondsSinceEpoch,
      'source': {
        'type': 'user',
        'userId': _auth.userId,
      },
      'message': {
        'id': msgId,
        'type': 'sticker',
        'packageId': packageId,
        'stickerId': stickerId,
      },
    };

    final success = await _sendWebhookEvent(botId, event);

    return ChatMessage(
      id: msgId,
      botId: botId,
      userId: _auth.userId,
      isUser: true,
      messageType: 'sticker',
      content: {
        'packageId': packageId,
        'stickerId': stickerId,
      },
      timestamp: now,
      status: success ? 'sent' : 'failed',
    );
  }

  /// Send a Location message.
  Future<ChatMessage?> sendLocationMessage(
    String botId, {
    required String title,
    required String address,
    required double latitude,
    required double longitude,
  }) async {
    final msgId = 'msg_${_uuid.v4()}';
    final replyToken = 'reply_${_uuid.v4()}';
    final now = DateTime.now();

    final event = {
      'type': 'message',
      'replyToken': replyToken,
      'timestamp': now.millisecondsSinceEpoch,
      'source': {
        'type': 'user',
        'userId': _auth.userId,
      },
      'message': {
        'id': msgId,
        'type': 'location',
        'title': title,
        'address': address,
        'latitude': latitude,
        'longitude': longitude,
      },
    };

    final success = await _sendWebhookEvent(botId, event);

    return ChatMessage(
      id: msgId,
      botId: botId,
      userId: _auth.userId,
      isUser: true,
      messageType: 'location',
      content: {
        'title': title,
        'address': address,
        'latitude': latitude,
        'longitude': longitude,
      },
      timestamp: now,
      status: success ? 'sent' : 'failed',
    );
  }


  /// Upload a media file and send the corresponding webhook event.
  ///
  /// [mediaType]：'image'、'audio'、'video' 或 'file'。
  /// 檔案訊息需提供 [fileName] 與 [fileSize]（與 LINE 的 file 事件格式相同）。
  Future<ChatMessage?> uploadAndSendMedia(
    String botId,
    File file,
    String mediaType, {
    int duration = 0,
    String? fileName,
    int? fileSize,
  }) async {
    final msgId = 'msg_${_uuid.v4()}';
    final replyToken = 'reply_${_uuid.v4()}';
    final now = DateTime.now();

    try {
      // 1. Upload to /upload
      final uri = Uri.parse('$_baseUrl/upload');
      final request = http.MultipartRequest('POST', uri)
        ..headers.addAll(_auth.authHeaders)
        ..fields['userId'] = _auth.userId
        ..fields['messageId'] = msgId
        ..files.add(await http.MultipartFile.fromPath('file', file.path));

      final streamedResponse = await request.send().timeout(const Duration(seconds: 30));
      final response = await http.Response.fromStream(streamedResponse);

      if (response.statusCode != 200) {
        return null;
      }

      final resData = jsonDecode(response.body);
      final mediaUrl = resData['url'] ?? '';

      // 2. Send webhook event
      final messageContent = <String, dynamic>{
        'id': msgId,
        'type': mediaType,
      };

      if (mediaType == 'file') {
        messageContent['fileName'] = fileName ?? file.uri.pathSegments.last;
        messageContent['fileSize'] = fileSize ?? await file.length();
      } else {
        messageContent['contentProvider'] = {'type': 'line'};
      }
      if (mediaType == 'audio' || mediaType == 'video') {
        messageContent['duration'] = duration;
      }

      final event = {
        'type': 'message',
        'replyToken': replyToken,
        'timestamp': now.millisecondsSinceEpoch,
        'source': {
          'type': 'user',
          'userId': _auth.userId,
        },
        'message': messageContent,
      };

      final success = await _sendWebhookEvent(botId, event);

      return ChatMessage(
        id: msgId,
        botId: botId,
        userId: _auth.userId,
        isUser: true,
        messageType: mediaType,
        content: {
          'originalContentUrl': mediaUrl,
          if (mediaType == 'image') 'previewImageUrl': mediaUrl,
          if (mediaType == 'audio' || mediaType == 'video') 'duration': duration,
          if (mediaType == 'file') 'fileName': messageContent['fileName'],
          if (mediaType == 'file') 'fileSize': messageContent['fileSize'],
        },
        timestamp: now,
        status: success ? 'sent' : 'failed',
      );
    } catch (e) {
      return null;
    }
  }

  /// 取得目前使用者的 Rich Menu（沒有時回傳 null）。
  Future<Map<String, dynamic>?> fetchRichMenu(String botId) async {
    try {
      final uri = Uri.parse('$_baseUrl/richmenu/current'
          '?userId=${Uri.encodeQueryComponent(_auth.userId)}'
          '&botId=${Uri.encodeQueryComponent(botId)}');
      final res = await http.get(
        uri,
        headers: _auth.authHeaders,
      ).timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        if (data is Map && data['richMenu'] is Map) {
          return Map<String, dynamic>.from(data['richMenu'] as Map);
        }
      }
    } catch (_) {}
    return null;
  }

  /// richmenuswitch 動作：切換到別名指向的選單。
  /// 回傳 (status, 新選單)；status 與 LINE 相同為 SUCCESS / RICHMENU_ALIAS_ID_NOTFOUND / FAILED。
  Future<(String, Map<String, dynamic>?)> switchRichMenu(String botId, String aliasId) async {
    try {
      final res = await http.post(
        Uri.parse('$_baseUrl/richmenu/switch'),
        headers: {
          'Content-Type': 'application/json',
          ..._auth.authHeaders,
        },
        body: jsonEncode({'userId': _auth.userId, 'botId': botId, 'richMenuAliasId': aliasId}),
      ).timeout(const Duration(seconds: 8));
      final data = jsonDecode(res.body);
      if (data is Map) {
        final status = (data['status'] ?? 'FAILED').toString();
        final menu = data['richMenu'] is Map
            ? Map<String, dynamic>.from(data['richMenu'] as Map)
            : null;
        return (status, menu);
      }
    } catch (_) {}
    return ('FAILED', null);
  }

  /// Fetch list of available stickers from Server.
  Future<List<Map<String, dynamic>>> fetchStickerPackages() async {
    try {
      final uri = Uri.parse('$_baseUrl/stickers/list');
      final res = await http.get(uri).timeout(const Duration(seconds: 5));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        return List<Map<String, dynamic>>.from(data['packages'] ?? []);
      }
    } catch (_) {}
    return [];
  }

  /// Fetch remote message history.
  Future<List<ChatMessage>> fetchHistory(String botId, {int limit = 50}) async {
    try {
      final uri = Uri.parse('$_baseUrl/history'
          '?userId=${Uri.encodeQueryComponent(_auth.userId)}'
          '&botId=${Uri.encodeQueryComponent(botId)}&limit=$limit');
      final res = await http.get(
        uri,
        headers: _auth.authHeaders,
      ).timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        final rawList = data['messages'] as List? ?? [];
        return rawList.map((m) {
          return ChatMessage(
            id: m['message_id'] ?? '',
            botId: botId,
            userId: m['user_id'] ?? '',
            isUser: m['direction'] == 'incoming',
            messageType: m['message_type'] ?? 'text',
            content: m['content'],
            timestamp: DateTime.fromMillisecondsSinceEpoch(m['created_at'] ?? 0),
            status: 'sent',
          );
        }).toList();
      }
    } catch (_) {}
    return [];
  }
}
