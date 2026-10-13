import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import '../theme/app_theme.dart';

typedef ActionCallback = void Function(Map<String, dynamic> action);

/// 渲染 TemplateSendMessage：Buttons、Confirm、Carousel（與 Messaging API 格式相容）。
class TemplateMessageWidget extends StatelessWidget {
  final Map<String, dynamic> templateData;
  final ActionCallback onAction;

  const TemplateMessageWidget({
    super.key,
    required this.templateData,
    required this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    final type = templateData['type'] ?? '';

    switch (type) {
      case 'buttons':
        return _buildButtonsCard(context, templateData);
      case 'confirm':
        return _buildConfirmCard(context, templateData);
      case 'carousel':
        return _buildCarousel(context, templateData);
      default:
        return Text(templateData['text']?.toString() ?? '不支援的模板訊息');
    }
  }

  static List<Map<String, dynamic>> _actionsOf(Map<String, dynamic> data) {
    final raw = data['actions'] as List? ?? [];
    return raw.whereType<Map>().map((m) => Map<String, dynamic>.from(m)).toList();
  }

  static String _labelOf(Map<String, dynamic> act, String fallback) {
    return (act['label'] ?? act['text'] ?? fallback).toString();
  }

  BoxDecoration _cardDecoration(BuildContext context) {
    final palette = ChatPalette.of(context);
    return BoxDecoration(
      color: palette.botBubble,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: palette.botBubbleBorder),
    );
  }

  Widget _buildButtonsCard(BuildContext context, Map<String, dynamic> data) {
    final palette = ChatPalette.of(context);
    final scheme = Theme.of(context).colorScheme;
    final imageUrl = data['thumbnailImageUrl'];
    final title = data['title'];
    final text = (data['text'] ?? '').toString();
    final actions = _actionsOf(data);

    return Container(
      width: 264,
      decoration: _cardDecoration(context),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (imageUrl != null && imageUrl.toString().isNotEmpty)
            CachedNetworkImage(
              imageUrl: imageUrl.toString(),
              height: 140,
              fit: BoxFit.cover,
              placeholder: (_, __) => Container(
                height: 140,
                color: scheme.surfaceContainerHighest,
                child: const Center(child: CircularProgressIndicator(strokeWidth: 2)),
              ),
              errorWidget: (_, __, ___) => Container(
                height: 140,
                color: scheme.surfaceContainerHighest,
                child: Icon(Icons.broken_image_outlined, color: scheme.outline),
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (title != null && title.toString().isNotEmpty) ...[
                  Text(
                    title.toString(),
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 16,
                      color: palette.onBotBubble,
                    ),
                  ),
                  const SizedBox(height: 4),
                ],
                Text(
                  text,
                  style: TextStyle(color: palette.meta, fontSize: 14, height: 1.4),
                ),
              ],
            ),
          ),
          if (actions.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (var i = 0; i < actions.length; i++) ...[
                    if (i > 0) const SizedBox(height: 6),
                    _ActionButton(
                      label: _labelOf(actions[i], '選項'),
                      primary: i == 0,
                      onPressed: () => onAction(actions[i]),
                    ),
                  ],
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildConfirmCard(BuildContext context, Map<String, dynamic> data) {
    final palette = ChatPalette.of(context);
    final text = (data['text'] ?? '').toString();
    final actions = _actionsOf(data);

    return Container(
      width: 264,
      decoration: _cardDecoration(context),
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            text,
            style: TextStyle(fontSize: 15, color: palette.onBotBubble, height: 1.4),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              for (var i = 0; i < actions.length; i++) ...[
                if (i > 0) const SizedBox(width: 8),
                Expanded(
                  child: _ActionButton(
                    label: _labelOf(actions[i], i == 0 ? '確認' : '取消'),
                    primary: i == 0,
                    onPressed: () => onAction(actions[i]),
                  ),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildCarousel(BuildContext context, Map<String, dynamic> data) {
    final raw = data['columns'] as List? ?? [];
    final columns = raw.whereType<Map>().map((m) => Map<String, dynamic>.from(m)).toList();

    // 不固定高度，讓每張卡片依內容決定高度，避免內容被截斷
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.only(right: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < columns.length; i++) ...[
            if (i > 0) const SizedBox(width: 10),
            _buildButtonsCard(context, columns[i]),
          ],
        ],
      ),
    );
  }
}

/// 模板訊息中的動作按鈕：第一個為主要按鈕，其餘為次要按鈕。
class _ActionButton extends StatelessWidget {
  final String label;
  final bool primary;
  final VoidCallback onPressed;

  const _ActionButton({
    required this.label,
    required this.primary,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(10));
    const padding = EdgeInsets.symmetric(horizontal: 12, vertical: 10);
    final child = Text(
      label,
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: const TextStyle(fontWeight: FontWeight.w600),
    );

    if (primary) {
      return FilledButton.tonal(
        style: FilledButton.styleFrom(shape: shape, padding: padding),
        onPressed: onPressed,
        child: child,
      );
    }
    return OutlinedButton(
      style: OutlinedButton.styleFrom(shape: shape, padding: padding),
      onPressed: onPressed,
      child: child,
    );
  }
}
