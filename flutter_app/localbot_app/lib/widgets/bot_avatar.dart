import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../services/auth_service.dart';

/// LocalBot 的 Bot 頭像：管理員在後台上傳了頭像就顯示圖片，否則顯示圓角方形 + 機器人圖示。
class BotAvatar extends StatelessWidget {
  final double size;

  /// 伺服器給的頭像網址（通常是 `/avatars/xxx.png` 這種相對路徑）；空字串或 null 表示沒有頭像
  final String? url;

  const BotAvatar({super.key, this.size = 32, this.url});

  /// 相對路徑接上目前的伺服器網址
  static String? resolve(String? url) {
    if (url == null || url.isEmpty) return null;
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
    final base = AuthService().baseUrl;
    if (base.isEmpty) return null;
    return url.startsWith('/') ? '$base$url' : '$base/$url';
  }

  @override
  Widget build(BuildContext context) {
    final radius = BorderRadius.circular(size * 0.32);
    final fallback = _placeholder(context, radius);
    final full = resolve(url);
    if (full == null) return fallback;
    return ClipRRect(
      borderRadius: radius,
      child: CachedNetworkImage(
        imageUrl: full,
        width: size,
        height: size,
        fit: BoxFit.cover,
        placeholder: (_, __) => fallback,
        errorWidget: (_, __, ___) => fallback,
      ),
    );
  }

  Widget _placeholder(BuildContext context, BorderRadius radius) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        borderRadius: radius,
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [scheme.primary, scheme.tertiary],
        ),
      ),
      child: Icon(
        Icons.smart_toy_rounded,
        color: scheme.onPrimary,
        size: size * 0.58,
      ),
    );
  }
}
