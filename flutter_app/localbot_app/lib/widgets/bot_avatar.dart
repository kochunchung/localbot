import 'package:flutter/material.dart';

/// LocalBot 的 Bot 頭像：圓角方形 + 機器人圖示。
class BotAvatar extends StatelessWidget {
  final double size;

  const BotAvatar({super.key, this.size = 32});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(size * 0.32),
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
