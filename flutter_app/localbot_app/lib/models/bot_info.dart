/// 使用者加入的一個 Bot（好友）。對應伺服器 /me 與 /join 回傳的 bot 物件。
class BotInfo {
  final String botId;
  final String name;
  final String description;

  /// 頭像網址（伺服器給的相對路徑，例如 `/avatars/xxx.png`；沒有頭像時為空字串）
  final String avatarUrl;
  final bool blocked;
  final int? lastMessageAt;

  const BotInfo({
    required this.botId,
    required this.name,
    this.description = '',
    this.avatarUrl = '',
    this.blocked = false,
    this.lastMessageAt,
  });

  factory BotInfo.fromJson(Map<dynamic, dynamic> json) {
    final last = json['lastMessageAt'];
    return BotInfo(
      botId: (json['botId'] ?? '').toString(),
      name: (json['name'] ?? '').toString(),
      description: (json['description'] ?? '').toString(),
      avatarUrl: (json['avatarUrl'] ?? '').toString(),
      blocked: json['blocked'] == true,
      lastMessageAt: last is num ? last.toInt() : null,
    );
  }

  Map<String, dynamic> toJson() => {
        'botId': botId,
        'name': name,
        'description': description,
        'avatarUrl': avatarUrl,
        'blocked': blocked,
        if (lastMessageAt != null) 'lastMessageAt': lastMessageAt,
      };

  BotInfo copyWith({bool? blocked, int? lastMessageAt}) => BotInfo(
        botId: botId,
        name: name,
        description: description,
        avatarUrl: avatarUrl,
        blocked: blocked ?? this.blocked,
        lastMessageAt: lastMessageAt ?? this.lastMessageAt,
      );
}
