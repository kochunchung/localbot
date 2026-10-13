import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';
import 'auth_service.dart';
import '../models/message.dart';

/// Service for communicating with LocalBot Server via HTTP REST endpoints.
class ApiService {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  final AuthService _auth = AuthService();
  final Uuid _uuid = const Uuid();

  String get _baseUrl => _auth.serverUrl.replaceAll(RegExp(r'/+$'), '');

  /// Send a LINE-compatible Webhook event to /callback.
  Future<bool> _sendWebhookEvent(Map<String, dynamic> event) async {
    final payload = {
      'destination': 'localbot',
      'events': [event],
    };

    final body = jsonEncode(payload);
    final signature = _auth.signPayload(body);

    try {
      final uri = Uri.parse('$_baseUrl/callback');
      final response = await http.post(
        uri,
        headers: {
          'Content-Type': 'application/json',
          'X-LocalBot-Signature': signature,
          'X-Line-Signature': signature,
        },
        body: body,
      ).timeout(const Duration(seconds: 10));

      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  /// Send a plain text message.
  Future<ChatMessage?> sendTextMessage(String text) async {
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
      },
    };

    final success = await _sendWebhookEvent(event);

    return ChatMessage(
      id: msgId,
      userId: _auth.userId,
      isUser: true,
      messageType: 'text',
      content: {'text': text},
      timestamp: now,
      status: success ? 'sent' : 'failed',
    );
  }

  /// Send a Postback action event (when user clicks template or flex button).
  Future<bool> sendPostback(String data, {String? displayText}) async {
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
      },
    };

    return await _sendWebhookEvent(event);
  }

  /// Send a Sticker message.
  Future<ChatMessage?> sendSticker(String packageId, String stickerId) async {
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

    final success = await _sendWebhookEvent(event);

    return ChatMessage(
      id: msgId,
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
  Future<ChatMessage?> sendLocationMessage({
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

    final success = await _sendWebhookEvent(event);

    return ChatMessage(
      id: msgId,
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


  /// Upload a media file (image or audio) and send the corresponding webhook event.
  Future<ChatMessage?> uploadAndSendMedia(
    File file,
    String mediaType, { // 'image' or 'audio'
    int duration = 0,
  }) async {
    final msgId = 'msg_${_uuid.v4()}';
    final replyToken = 'reply_${_uuid.v4()}';
    final now = DateTime.now();

    try {
      // 1. Upload to /upload
      final uri = Uri.parse('$_baseUrl/upload');
      final request = http.MultipartRequest('POST', uri)
        ..headers['X-LocalBot-Token'] = _auth.userToken
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
        'contentProvider': {'type': 'line'},
      };

      if (mediaType == 'audio') {
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

      final success = await _sendWebhookEvent(event);

      return ChatMessage(
        id: msgId,
        userId: _auth.userId,
        isUser: true,
        messageType: mediaType,
        content: {
          'originalContentUrl': mediaUrl,
          'previewImageUrl': mediaUrl,
          'duration': duration,
        },
        timestamp: now,
        status: success ? 'sent' : 'failed',
      );
    } catch (e) {
      return null;
    }
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
  Future<List<ChatMessage>> fetchHistory({int limit = 50}) async {
    try {
      final uri = Uri.parse('$_baseUrl/history?userId=${Uri.encodeQueryComponent(_auth.userId)}&limit=$limit');
      final res = await http.get(
        uri,
        headers: {'X-LocalBot-Token': _auth.userToken},
      ).timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        final rawList = data['messages'] as List? ?? [];
        return rawList.map((m) {
          return ChatMessage(
            id: m['message_id'] ?? '',
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
