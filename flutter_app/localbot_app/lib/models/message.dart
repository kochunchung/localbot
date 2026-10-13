import 'dart:convert';

/// Representation of a message in the chat timeline.
class ChatMessage {
  final String id;
  final String userId;
  final bool isUser;
  final String messageType; // 'text', 'image', 'audio', 'video', 'sticker', 'template', 'flex'
  final dynamic content; // Raw JSON map or String
  final DateTime timestamp;
  String status; // 'sending', 'sent', 'failed'

  ChatMessage({
    required this.id,
    required this.userId,
    required this.isUser,
    required this.messageType,
    required this.content,
    required this.timestamp,
    this.status = 'sent',
  });

  /// Convenient getter for text content
  String get text {
    if (content is String) return content;
    if (content is Map) {
      return content['text'] ?? content['altText'] ?? '';
    }
    return '';
  }

  /// Convenient getter for media URL (image, audio, etc.)
  String? get mediaUrl {
    if (content is Map) {
      return content['originalContentUrl'] ??
          content['previewImageUrl'] ??
          content['url'];
    }
    return null;
  }

  /// Convenient getter for duration
  int get duration {
    if (content is Map) {
      return content['duration'] ?? 0;
    }
    return 0;
  }

  /// Convenient getter for quickReply items
  List<dynamic>? get quickReplyItems {
    if (content is Map && content['quickReply'] != null) {
      final qr = content['quickReply'];
      if (qr is Map && qr['items'] is List) {
        return qr['items'] as List<dynamic>;
      }
    }
    return null;
  }

  /// Convenient getters for location message
  String get locationTitle {
    if (content is Map) {
      return content['title'] ?? '位置資訊';
    }
    return '位置資訊';
  }

  String get locationAddress {
    if (content is Map) {
      return content['address'] ?? '';
    }
    return '';
  }

  double get latitude {
    if (content is Map) {
      final lat = content['latitude'];
      if (lat is num) return lat.toDouble();
      if (lat is String) return double.tryParse(lat) ?? 0.0;
    }
    return 0.0;
  }

  double get longitude {
    if (content is Map) {
      final lng = content['longitude'];
      if (lng is num) return lng.toDouble();
      if (lng is String) return double.tryParse(lng) ?? 0.0;
    }
    return 0.0;
  }

  /// Convert to SQLite Database map
  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'user_id': userId,
      'is_user': isUser ? 1 : 0,
      'message_type': messageType,
      'content': content is String ? content : jsonEncode(content),
      'timestamp': timestamp.millisecondsSinceEpoch,
      'status': status,
    };
  }

  /// Create from SQLite Database map
  factory ChatMessage.fromMap(Map<String, dynamic> map) {
    dynamic parsedContent;
    final rawContent = map['content'];
    if (rawContent is String) {
      try {
        parsedContent = jsonDecode(rawContent);
      } catch (_) {
        parsedContent = rawContent;
      }
    } else {
      parsedContent = rawContent;
    }

    return ChatMessage(
      id: map['id'] ?? '',
      userId: map['user_id'] ?? '',
      isUser: (map['is_user'] ?? 1) == 1,
      messageType: map['message_type'] ?? 'text',
      content: parsedContent,
      timestamp: DateTime.fromMillisecondsSinceEpoch(map['timestamp'] ?? 0),
      status: map['status'] ?? 'sent',
    );
  }

  /// Create from Socket.IO incoming bot_message
  factory ChatMessage.fromSocketPayload(Map<String, dynamic> payload) {
    final rawContent = payload['content'] ?? {};
    final msgType = payload['messageType'] ??
        (rawContent is Map ? rawContent['type'] : 'text') ??
        'text';

    return ChatMessage(
      id: payload['messageId'] ?? DateTime.now().millisecondsSinceEpoch.toString(),
      userId: payload['userId'] ?? '',
      isUser: (payload['direction'] ?? 'outgoing') == 'incoming',
      messageType: msgType,
      content: rawContent,
      timestamp: payload['createdAt'] != null
          ? DateTime.fromMillisecondsSinceEpoch(payload['createdAt'])
          : DateTime.now(),
      status: 'sent',
    );
  }
}
