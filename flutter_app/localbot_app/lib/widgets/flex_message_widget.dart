import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'template_widgets.dart'; // For ActionCallback

/// Flex Message 基本渲染（Bubble 與 Carousel，與 Messaging API 格式相容）。
/// Flex 卡片的顏色由 Bot 指定，因此卡片底色固定為白色以保持 Bot 設計的可讀性。
class FlexMessageWidget extends StatelessWidget {
  final Map<String, dynamic> flexContents;
  final ActionCallback onAction;

  const FlexMessageWidget({
    super.key,
    required this.flexContents,
    required this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    final type = flexContents['type'] ?? 'bubble';

    if (type == 'carousel') {
      final raw = flexContents['contents'] as List? ?? [];
      final bubbles = raw.whereType<Map>().map((m) => Map<String, dynamic>.from(m)).toList();
      // 不固定高度，避免內容較長的卡片被截斷
      return SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.only(right: 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < bubbles.length; i++) ...[
              if (i > 0) const SizedBox(width: 10),
              _buildBubble(context, bubbles[i]),
            ],
          ],
        ),
      );
    } else {
      return _buildBubble(context, flexContents);
    }
  }

  Widget _buildBubble(BuildContext context, Map<String, dynamic> bubble) {
    final header = bubble['header'];
    final hero = bubble['hero'];
    final body = bubble['body'];
    final footer = bubble['footer'];

    return Container(
      width: 270,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE3E5EE)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (header != null) _buildBox(context, header),
          if (hero != null) _buildHero(context, hero),
          if (body != null) _buildBox(context, body),
          if (footer != null) _buildBox(context, footer),
        ],
      ),
    );
  }

  Widget _buildHero(BuildContext context, Map<String, dynamic> hero) {
    final type = hero['type'] ?? '';
    if (type == 'image') {
      return _buildImage(context, hero);
    }
    return _buildBox(context, hero);
  }

  Widget _buildBox(BuildContext context, Map<String, dynamic> box) {
    final layout = box['layout'] ?? 'vertical';
    final contents = (box['contents'] as List? ?? [])
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();
    final bgColor = _parseColor(box['backgroundColor']);

    final children = contents.map((item) => _buildComponent(context, item)).toList();

    Widget boxContent;
    if (layout == 'horizontal') {
      boxContent = Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: children.map((c) => Expanded(child: c)).toList(),
      );
    } else {
      boxContent = Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: children,
      );
    }

    return Container(
      color: bgColor,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      child: boxContent,
    );
  }

  Widget _buildComponent(BuildContext context, Map<String, dynamic> item) {
    final type = item['type'] ?? '';

    switch (type) {
      case 'box':
        return _buildBox(context, item);
      case 'text':
        return _buildText(context, item);
      case 'image':
        return _buildImage(context, item);
      case 'button':
        return _buildButton(context, item);
      case 'separator':
        return const Divider(height: 12, thickness: 1);
      default:
        return const SizedBox.shrink();
    }
  }

  Widget _buildText(BuildContext context, Map<String, dynamic> item) {
    final text = item['text'] ?? '';
    final weight = item['weight'] == 'bold' ? FontWeight.bold : FontWeight.normal;
    final color = _parseColor(item['color']) ?? Colors.black87;
    final wrap = item['wrap'] == true;
    final sizeStr = item['size'] ?? 'md';

    double fontSize = 14;
    switch (sizeStr) {
      case 'xxs': fontSize = 10; break;
      case 'xs': fontSize = 12; break;
      case 'sm': fontSize = 13; break;
      case 'md': fontSize = 15; break;
      case 'lg': fontSize = 17; break;
      case 'xl': fontSize = 20; break;
      case 'xxl': fontSize = 24; break;
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Text(
        text,
        style: TextStyle(
          fontSize: fontSize,
          fontWeight: weight,
          color: color,
        ),
        softWrap: wrap,
      ),
    );
  }

  Widget _buildImage(BuildContext context, Map<String, dynamic> item) {
    final url = item['url'] ?? '';
    if (url.isEmpty) return const SizedBox.shrink();

    return CachedNetworkImage(
      imageUrl: url,
      height: 150,
      fit: BoxFit.cover,
      placeholder: (_, __) => Container(
        height: 150,
        color: Colors.grey.shade200,
        child: const Center(child: CircularProgressIndicator(strokeWidth: 2)),
      ),
      errorWidget: (_, __, ___) => Container(
        height: 150,
        color: Colors.grey.shade300,
        child: const Icon(Icons.image, color: Colors.grey),
      ),
    );
  }

  Widget _buildButton(BuildContext context, Map<String, dynamic> item) {
    final action = item['action'] ?? {};
    final label = action['label'] ?? '按鈕';
    final style = item['style'] ?? 'link';
    final color = _parseColor(item['color']) ?? Theme.of(context).colorScheme.primary;

    if (style == 'primary') {
      return FilledButton(
        style: FilledButton.styleFrom(
          backgroundColor: color,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ),
        onPressed: () => onAction(Map<String, dynamic>.from(action)),
        child: Text(label),
      );
    } else if (style == 'secondary') {
      return OutlinedButton(
        style: OutlinedButton.styleFrom(
          foregroundColor: color,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ),
        onPressed: () => onAction(Map<String, dynamic>.from(action)),
        child: Text(label, style: const TextStyle(fontWeight: FontWeight.w600)),
      );
    } else {
      return TextButton(
        style: TextButton.styleFrom(
          foregroundColor: color,
        ),
        onPressed: () => onAction(Map<String, dynamic>.from(action)),
        child: Text(label, style: const TextStyle(fontWeight: FontWeight.w600)),
      );
    }
  }

  Color? _parseColor(dynamic hexString) {
    if (hexString == null || hexString is! String || !hexString.startsWith('#')) {
      return null;
    }
    try {
      final hex = hexString.replaceAll('#', '');
      if (hex.length == 6) {
        return Color(int.parse('FF$hex', radix: 16));
      } else if (hex.length == 8) {
        return Color(int.parse(hex, radix: 16));
      }
    } catch (_) {}
    return null;
  }
}
