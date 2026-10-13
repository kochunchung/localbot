import 'package:flutter/material.dart';

/// LocalBot 品牌色與主題。
///
/// 想換成自己的品牌色，只要改 [AppTheme.brandSeed] 即可，
/// 其餘顏色會由 Material 3 自動推導。
class AppTheme {
  AppTheme._();

  /// 品牌主色（靛藍）
  static const Color brandSeed = Color(0xFF4F46E5);

  /// 連線狀態語意色
  static const Color statusOnline = Color(0xFF16A34A);
  static const Color statusConnecting = Color(0xFFF59E0B);
  static const Color statusOffline = Color(0xFFDC2626);

  static ThemeData light() => _build(Brightness.light);
  static ThemeData dark() => _build(Brightness.dark);

  static ThemeData _build(Brightness brightness) {
    final scheme = ColorScheme.fromSeed(
      seedColor: brandSeed,
      brightness: brightness,
    );
    final isDark = brightness == Brightness.dark;

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: scheme.surface,
      snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
      dividerTheme: DividerThemeData(
        color: scheme.outlineVariant.withValues(alpha: 0.6),
        thickness: 1,
        space: 1,
      ),
      extensions: <ThemeExtension<dynamic>>[
        isDark ? ChatPalette.dark(scheme) : ChatPalette.light(scheme),
      ],
    );
  }
}

/// 聊天室專用顏色（泡泡、背景、時間文字）。
@immutable
class ChatPalette extends ThemeExtension<ChatPalette> {
  final Color background;
  final Color userBubble;
  final Color onUserBubble;
  final Color botBubble;
  final Color onBotBubble;
  final Color botBubbleBorder;
  final Color meta;

  const ChatPalette({
    required this.background,
    required this.userBubble,
    required this.onUserBubble,
    required this.botBubble,
    required this.onBotBubble,
    required this.botBubbleBorder,
    required this.meta,
  });

  factory ChatPalette.light(ColorScheme s) => ChatPalette(
        background: const Color(0xFFF5F6FA),
        userBubble: s.primary,
        onUserBubble: s.onPrimary,
        botBubble: Colors.white,
        onBotBubble: const Color(0xFF1B1C22),
        botBubbleBorder: const Color(0xFFE3E5EE),
        meta: const Color(0xFF7A7F91),
      );

  factory ChatPalette.dark(ColorScheme s) => ChatPalette(
        background: const Color(0xFF111218),
        userBubble: s.primary,
        onUserBubble: s.onPrimary,
        botBubble: const Color(0xFF1E2029),
        onBotBubble: const Color(0xFFE6E7EE),
        botBubbleBorder: const Color(0xFF2C2F3B),
        meta: const Color(0xFF9094A6),
      );

  /// 方便取得：`ChatPalette.of(context)`
  static ChatPalette of(BuildContext context) {
    final theme = Theme.of(context);
    return theme.extension<ChatPalette>() ?? ChatPalette.light(theme.colorScheme);
  }

  @override
  ChatPalette copyWith({
    Color? background,
    Color? userBubble,
    Color? onUserBubble,
    Color? botBubble,
    Color? onBotBubble,
    Color? botBubbleBorder,
    Color? meta,
  }) {
    return ChatPalette(
      background: background ?? this.background,
      userBubble: userBubble ?? this.userBubble,
      onUserBubble: onUserBubble ?? this.onUserBubble,
      botBubble: botBubble ?? this.botBubble,
      onBotBubble: onBotBubble ?? this.onBotBubble,
      botBubbleBorder: botBubbleBorder ?? this.botBubbleBorder,
      meta: meta ?? this.meta,
    );
  }

  @override
  ChatPalette lerp(ThemeExtension<ChatPalette>? other, double t) {
    if (other is! ChatPalette) return this;
    return ChatPalette(
      background: Color.lerp(background, other.background, t)!,
      userBubble: Color.lerp(userBubble, other.userBubble, t)!,
      onUserBubble: Color.lerp(onUserBubble, other.onUserBubble, t)!,
      botBubble: Color.lerp(botBubble, other.botBubble, t)!,
      onBotBubble: Color.lerp(onBotBubble, other.onBotBubble, t)!,
      botBubbleBorder: Color.lerp(botBubbleBorder, other.botBubbleBorder, t)!,
      meta: Color.lerp(meta, other.meta, t)!,
    );
  }
}
