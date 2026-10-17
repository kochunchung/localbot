import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import 'template_widgets.dart'; // For ActionCallback

/// Rich Menu（聊天室下方的圖文選單）。
///
/// [menu] 為伺服器 /richmenu/current 回傳的資料：
/// size、chatBarText、areas（bounds + action）、imageUrl。
class RichMenuPanel extends StatelessWidget {
  final Map<String, dynamic> menu;
  final ActionCallback onAction;
  final VoidCallback onCollapse;

  /// 選單最多佔螢幕高度的比例，避免在橫向或小螢幕擠掉聊天內容
  static const double maxHeightFactor = 0.4;

  const RichMenuPanel({
    super.key,
    required this.menu,
    required this.onAction,
    required this.onCollapse,
  });

  static double _num(dynamic v, double fallback) =>
      v is num ? v.toDouble() : double.tryParse('$v') ?? fallback;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final size = menu['size'] is Map ? menu['size'] as Map : const {};
    final menuWidth = _num(size['width'], 2500);
    final menuHeight = _num(size['height'], 1686);
    final areas = menu['areas'] is List ? menu['areas'] as List : const [];
    final imageUrl = (menu['imageUrl'] ?? '').toString();
    final title = (menu['chatBarText'] ?? '選單').toString();
    final maxHeight = MediaQuery.sizeOf(context).height * maxHeightFactor;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        // 標題列：點擊收合（對應 LINE 的 chatBarText）
        InkWell(
          onTap: onCollapse,
          child: Container(
            height: 32,
            width: double.infinity,
            decoration: BoxDecoration(
              border: Border(top: BorderSide(color: scheme.outlineVariant.withValues(alpha: 0.6))),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  title,
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: scheme.onSurfaceVariant),
                ),
                const SizedBox(width: 4),
                Icon(Icons.keyboard_arrow_down_rounded, size: 18, color: scheme.onSurfaceVariant),
              ],
            ),
          ),
        ),
        LayoutBuilder(
          builder: (context, constraints) {
            // 依比例縮放，太高時等比縮小並置中
            var width = constraints.maxWidth;
            var height = width * menuHeight / menuWidth;
            if (height > maxHeight) {
              height = maxHeight;
              width = height * menuWidth / menuHeight;
            }
            final scale = width / menuWidth;

            return Center(
              child: SizedBox(
                width: width,
                height: height,
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: imageUrl.isEmpty
                          ? ColoredBox(color: scheme.surfaceContainerHighest)
                          : CachedNetworkImage(
                              imageUrl: imageUrl,
                              fit: BoxFit.fill,
                              placeholder: (_, __) => ColoredBox(color: scheme.surfaceContainerHighest),
                              errorWidget: (_, __, ___) => ColoredBox(
                                color: scheme.surfaceContainerHighest,
                                child: Icon(Icons.broken_image_outlined, color: scheme.outline),
                              ),
                            ),
                    ),
                    for (final raw in areas)
                      if (raw is Map && raw['bounds'] is Map && raw['action'] is Map)
                        _area(raw['bounds'] as Map, Map<String, dynamic>.from(raw['action'] as Map), scale),
                  ],
                ),
              ),
            );
          },
        ),
      ],
    );
  }

  Widget _area(Map bounds, Map<String, dynamic> action, double scale) {
    final label = (action['label'] ?? action['text'] ?? '').toString();
    return Positioned(
      left: _num(bounds['x'], 0) * scale,
      top: _num(bounds['y'], 0) * scale,
      width: _num(bounds['width'], 0) * scale,
      height: _num(bounds['height'], 0) * scale,
      child: Semantics(
        button: true,
        label: label,
        child: Material(
          color: Colors.transparent,
          child: InkWell(onTap: () => onAction(action)),
        ),
      ),
    );
  }
}
