import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'bot_avatar.dart';

/// Bot 呼叫 show_loading_animation 時顯示的「輸入中」泡泡（三個跳動的點）。
class TypingIndicator extends StatefulWidget {
  /// Bot 頭像網址（見 [BotAvatar.url]）
  final String? avatarUrl;

  const TypingIndicator({super.key, this.avatarUrl});

  @override
  State<TypingIndicator> createState() => _TypingIndicatorState();
}

class _TypingIndicatorState extends State<TypingIndicator>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1200),
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final palette = ChatPalette.of(context);

    return Semantics(
      container: true,
      liveRegion: true,
      label: 'Bot 正在輸入',
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            BotAvatar(size: 32, url: widget.avatarUrl),
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
              decoration: BoxDecoration(
                color: palette.botBubble,
                border: Border.all(color: palette.botBubbleBorder),
                borderRadius: const BorderRadius.only(
                  topLeft: Radius.circular(6),
                  topRight: Radius.circular(18),
                  bottomLeft: Radius.circular(18),
                  bottomRight: Radius.circular(18),
                ),
              ),
              child: AnimatedBuilder(
                animation: _controller,
                builder: (context, _) {
                  return Row(
                    mainAxisSize: MainAxisSize.min,
                    children: List.generate(3, (i) {
                      // 每個點錯開 0.2 的相位，形成波浪
                      final t = (_controller.value - i * 0.2) % 1.0;
                      final lift = t < 0.5 ? (t * 2) : (2 - t * 2);
                      return Padding(
                        padding: EdgeInsets.only(left: i == 0 ? 0 : 5),
                        child: Transform.translate(
                          offset: Offset(0, -3 * lift),
                          child: Container(
                            width: 7,
                            height: 7,
                            decoration: BoxDecoration(
                              color: palette.meta.withValues(alpha: 0.5 + 0.5 * lift),
                              shape: BoxShape.circle,
                            ),
                          ),
                        ),
                      );
                    }),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
