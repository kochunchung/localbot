import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../models/message.dart';
import '../screens/video_player_screen.dart';
import '../theme/app_theme.dart';
import 'template_widgets.dart';

/// 把位元組轉成易讀的大小，例如 1.2 MB。
String formatFileSize(int bytes) {
  if (bytes <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  var size = bytes.toDouble();
  var unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit++;
  }
  final text = unit == 0 ? size.toStringAsFixed(0) : size.toStringAsFixed(size < 10 ? 1 : 0);
  return '$text ${units[unit]}';
}

String _formatDuration(int ms) {
  if (ms <= 0) return '';
  final d = Duration(milliseconds: ms);
  final m = d.inMinutes.toString().padLeft(2, '0');
  final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
  return '$m:$s';
}

void openVideoPlayer(BuildContext context, String url) {
  Navigator.push(
    context,
    MaterialPageRoute(builder: (_) => VideoPlayerScreen(url: url)),
  );
}

// ============================================================================
// 影片訊息
// ============================================================================
class VideoMessageBubble extends StatelessWidget {
  final ChatMessage message;

  const VideoMessageBubble({super.key, required this.message});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final url = message.originalUrl ?? message.mediaUrl ?? '';
    final preview = message.previewUrl ?? '';
    final hasPreview = preview != url && preview.startsWith('http');
    final duration = _formatDuration(message.duration);

    return Semantics(
      button: true,
      label: '播放影片',
      child: GestureDetector(
        onTap: url.isEmpty ? null : () => openVideoPlayer(context, url),
        child: Container(
          width: 220,
          height: 160,
          decoration: BoxDecoration(
            color: const Color(0xFF1B1C22),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.5)),
          ),
          clipBehavior: Clip.antiAlias,
          child: Stack(
            fit: StackFit.expand,
            children: [
              if (hasPreview)
                CachedNetworkImage(
                  imageUrl: preview,
                  fit: BoxFit.cover,
                  errorWidget: (_, __, ___) => const SizedBox.shrink(),
                ),
              Container(color: Colors.black.withValues(alpha: 0.25)),
              const Center(
                child: Icon(Icons.play_circle_fill_rounded, size: 56, color: Colors.white),
              ),
              if (duration.isNotEmpty)
                Positioned(
                  right: 8,
                  bottom: 8,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: Colors.black54,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      duration,
                      style: const TextStyle(color: Colors.white, fontSize: 12),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

// ============================================================================
// 檔案訊息
// ============================================================================
class FileMessageBubble extends StatelessWidget {
  final ChatMessage message;
  final bool isUser;

  /// 點擊後開啟下載連結（由聊天畫面負責實際開啟）
  final ActionCallback onAction;

  /// 泡泡外框圓角；由聊天泡泡傳入，讓檔案訊息和文字訊息的形狀（含對話尾巴那一角）一致
  final BorderRadius? borderRadius;

  const FileMessageBubble({
    super.key,
    required this.message,
    required this.isUser,
    required this.onAction,
    this.borderRadius,
  });

  IconData _iconFor(String name) {
    final ext = name.contains('.') ? name.split('.').last.toLowerCase() : '';
    return switch (ext) {
      'pdf' => Icons.picture_as_pdf_rounded,
      'doc' || 'docx' || 'odt' || 'txt' || 'rtf' || 'md' => Icons.description_rounded,
      'xls' || 'xlsx' || 'ods' || 'csv' => Icons.table_chart_rounded,
      'ppt' || 'pptx' || 'odp' => Icons.slideshow_rounded,
      'zip' || 'rar' || '7z' => Icons.folder_zip_rounded,
      'mp3' || 'm4a' || 'wav' || 'aac' => Icons.audio_file_rounded,
      'mp4' || 'mov' || 'avi' || 'mkv' => Icons.video_file_rounded,
      'jpg' || 'jpeg' || 'png' || 'gif' || 'webp' => Icons.image_rounded,
      _ => Icons.insert_drive_file_rounded,
    };
  }

  @override
  Widget build(BuildContext context) {
    final palette = ChatPalette.of(context);
    final url = message.originalUrl ?? '';
    final canOpen = url.startsWith('http');
    final fg = isUser ? palette.onUserBubble : palette.onBotBubble;
    final sub = isUser ? palette.onUserBubble.withValues(alpha: 0.72) : palette.meta;
    final size = formatFileSize(message.fileSize);
    final radius = borderRadius ?? BorderRadius.circular(18);
    final name = message.fileName.isEmpty ? '檔案' : message.fileName;

    // 一整塊泡泡：左邊檔案圖示、右邊檔名與大小，兩側（自己 / Bot）用同一種版面，
    // 只換顏色；圖示底色取自文字色的淡色，不另外用一塊對比色，看起來比較一體。
    return Semantics(
      button: canOpen,
      label: '檔案 $name${size.isEmpty ? '' : '，$size'}',
      child: Material(
        color: isUser ? palette.userBubble : palette.botBubble,
        shape: RoundedRectangleBorder(
          borderRadius: radius,
          side: isUser ? BorderSide.none : BorderSide(color: palette.botBubbleBorder),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: canOpen ? () => onAction({'type': 'uri', 'uri': url}) : null,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minWidth: 200, maxWidth: 260),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 11, 16, 11),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Container(
                    width: 42,
                    height: 42,
                    decoration: BoxDecoration(
                      color: fg.withValues(alpha: 0.10),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Icon(_iconFor(name), color: fg.withValues(alpha: 0.85), size: 24),
                  ),
                  const SizedBox(width: 12),
                  Flexible(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          name,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: fg,
                            fontWeight: FontWeight.w600,
                            fontSize: 14.5,
                            height: 1.3,
                          ),
                        ),
                        if (size.isNotEmpty || canOpen) ...[
                          const SizedBox(height: 3),
                          Text(
                            [if (size.isNotEmpty) size, if (canOpen) '點擊開啟'].join('  ·  '),
                            style: TextStyle(color: sub, fontSize: 12, height: 1.2),
                          ),
                        ],
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ============================================================================
// Imagemap 訊息
// ============================================================================
class ImagemapMessageWidget extends StatelessWidget {
  final Map<String, dynamic> data;
  final ActionCallback onAction;

  static const double displayWidth = 260;

  const ImagemapMessageWidget({super.key, required this.data, required this.onAction});

  static double _num(dynamic v, [double fallback = 0]) =>
      v is num ? v.toDouble() : double.tryParse('$v') ?? fallback;

  /// 把 imagemap 動作轉成聊天畫面共用的動作格式
  static Map<String, dynamic>? _toChatAction(Map action) {
    switch (action['type']) {
      case 'uri':
        return {'type': 'uri', 'uri': action['linkUri'] ?? ''};
      case 'message':
        return {'type': 'message', 'text': action['text'] ?? ''};
      case 'clipboard':
        return {'type': 'clipboard', 'clipboardText': action['clipboardText'] ?? ''};
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final baseUrl = (data['baseUrl'] ?? '').toString().replaceAll(RegExp(r'/+$'), '');
    final baseSize = data['baseSize'] is Map ? data['baseSize'] as Map : const {};
    final baseWidth = _num(baseSize['width'], 1040);
    final baseHeight = _num(baseSize['height'], 1040);
    final scale = displayWidth / (baseWidth <= 0 ? 1040 : baseWidth);
    final height = baseHeight * scale;
    final actions = data['actions'] is List ? data['actions'] as List : const [];
    final video = data['video'] is Map ? data['video'] as Map : null;

    Widget placeholder() => Container(
          color: scheme.surfaceContainerHighest,
          child: Icon(Icons.broken_image_outlined, color: scheme.outline),
        );

    Positioned areaOf(Map? area, Widget child) {
      final a = area ?? const {};
      return Positioned(
        left: _num(a['x']) * scale,
        top: _num(a['y']) * scale,
        width: _num(a['width']) * scale,
        height: _num(a['height']) * scale,
        child: child,
      );
    }

    return Container(
      width: displayWidth,
      height: height,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.5)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          Positioned.fill(
            child: baseUrl.isEmpty
                ? placeholder()
                : CachedNetworkImage(
                    // 與 LINE 相同：{baseUrl}/{寬度}；失敗時改用 baseUrl 本身
                    imageUrl: '$baseUrl/1040',
                    fit: BoxFit.fill,
                    errorWidget: (_, __, ___) => CachedNetworkImage(
                      imageUrl: baseUrl,
                      fit: BoxFit.fill,
                      errorWidget: (_, __, ___) => placeholder(),
                    ),
                  ),
          ),
          for (final raw in actions)
            if (raw is Map && _toChatAction(raw) != null)
              areaOf(
                raw['area'] is Map ? raw['area'] as Map : null,
                Semantics(
                  button: true,
                  label: (raw['label'] ?? raw['text'] ?? raw['linkUri'] ?? '').toString(),
                  child: Material(
                    color: Colors.transparent,
                    child: InkWell(
                      onTap: () => onAction(_toChatAction(raw)!),
                    ),
                  ),
                ),
              ),
          if (video != null && (video['originalContentUrl'] ?? '').toString().isNotEmpty)
            areaOf(
              video['area'] is Map ? video['area'] as Map : null,
              GestureDetector(
                onTap: () => openVideoPlayer(context, video['originalContentUrl'].toString()),
                child: Container(
                  color: Colors.black26,
                  child: const Center(
                    child: Icon(Icons.play_circle_fill_rounded, size: 48, color: Colors.white),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
