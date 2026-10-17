import 'dart:convert';

/// Representation of a message in the chat timeline.
class ChatMessage {
  final String id;

  /// 這則訊息屬於哪個 Bot 的聊天室
  final String botId;
  final String userId;
  final bool isUser;
  final String messageType; // 'text', 'image', 'audio', 'video', 'sticker', 'template', 'flex'
  final dynamic content; // Raw JSON map or String
  final DateTime timestamp;
  String status; // 'sending', 'sent', 'failed'

  ChatMessage({
    required this.id,
    required this.botId,
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
      return (content['text'] ?? content['altText'] ?? '').toString();
    }
    return '';
  }

  /// Convenient getter for media URL (image, audio, etc.)
  String? get mediaUrl {
    if (content is Map) {
      return (content['originalContentUrl'] ??
              content['previewImageUrl'] ??
              content['url'])
          ?.toString();
    }
    return null;
  }

  /// 原始媒體網址（影片 / 檔案播放或下載用）
  String? get originalUrl {
    if (content is Map) return content['originalContentUrl']?.toString();
    return null;
  }

  /// 預覽圖網址（影片縮圖）
  String? get previewUrl {
    if (content is Map) return content['previewImageUrl']?.toString();
    return null;
  }

  /// 檔案訊息的檔名
  String get fileName {
    if (content is Map) {
      final name = content['fileName']?.toString();
      if (name != null && name.isNotEmpty) return name;
    }
    return '檔案';
  }

  /// 檔案訊息的大小（位元組）
  int get fileSize {
    if (content is Map) {
      final size = content['fileSize'];
      if (size is num) return size.toInt();
      if (size is String) return int.tryParse(size) ?? 0;
    }
    return 0;
  }

  /// Convenient getter for duration
  int get duration {
    if (content is Map) {
      final d = content['duration'];
      if (d is num) return d.toInt();
      if (d is String) return int.tryParse(d) ?? 0;
    }
    return 0;
  }

  /// 這則訊息引用（回覆）的訊息 id，與 LINE 的 quotedMessageId 相同
  String? get quotedMessageId {
    if (content is Map) {
      final q = content['quotedMessageId']?.toString();
      if (q != null && q.isNotEmpty) return q;
    }
    return null;
  }

  /// 一行文字摘要（回覆列、引用框使用）
  String get summary {
    switch (messageType) {
      case 'text':
        return text.replaceAll('\n', ' ');
      case 'image':
        return '[圖片]';
      case 'video':
        return '[影片]';
      case 'audio':
        return '[語音訊息]';
      case 'file':
        return '[檔案] $fileName';
      case 'sticker':
        return '[貼圖]';
      case 'location':
        return '[位置資訊] $locationTitle';
      default:
        final alt = text.replaceAll('\n', ' ');
        return alt.isNotEmpty ? alt : '[訊息]';
    }
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
      return content['title']?.toString() ?? '位置資訊';
    }
    return '位置資訊';
  }

  String get locationAddress {
    if (content is Map) {
      return content['address']?.toString() ?? '';
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
      'bot_id': botId,
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
      botId: map['bot_id'] ?? '',
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
      id: payload['messageId']?.toString() ??
          DateTime.now().millisecondsSinceEpoch.toString(),
      botId: payload['botId']?.toString() ?? '',
      userId: payload['userId']?.toString() ?? '',
      isUser: (payload['direction'] ?? 'outgoing') == 'incoming',
      messageType: msgType,
      content: rawContent,
      timestamp: payload['createdAt'] is num
          ? DateTime.fromMillisecondsSinceEpoch((payload['createdAt'] as num).toInt())
          : DateTime.now(),
      status: 'sent',
    );
  }
}
