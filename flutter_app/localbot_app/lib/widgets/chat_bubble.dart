import 'dart:io';
import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:intl/intl.dart';
import '../models/message.dart';
import '../services/auth_service.dart';
import '../theme/app_theme.dart';
import 'audio_player_widget.dart';
import 'bot_avatar.dart';
import 'template_widgets.dart';
import 'flex_message_widget.dart';
import 'media_bubbles.dart';

/// 單則訊息：依訊息類型渲染，並處理頭像、時間與傳送狀態。
class ChatBubble extends StatelessWidget {
  final ChatMessage message;
  final ActionCallback onAction;

  /// 同一串連續 Bot 訊息只在第一則顯示頭像
  final bool showAvatar;

  /// 同一分鐘內的連續訊息只在最後一則顯示時間
  final bool showMeta;

  /// 失敗時點擊重送（可選）
  final VoidCallback? onRetry;

  /// 長按訊息（顯示回覆 / 複製 / 刪除選單）
  final VoidCallback? onLongPress;

  /// 這則訊息引用的原訊息（找不到時為 null，只顯示「原訊息」）
  final ChatMessage? quoted;

  /// 原訊息的發送者名稱（「你」或 Bot 名稱）
  final String? quotedSender;

  /// Bot 頭像網址（見 [BotAvatar.url]）
  final String? botAvatarUrl;

  static const double _avatarSize = 32;
  static const double _avatarGap = 8;

  const ChatBubble({
    super.key,
    required this.message,
    required this.onAction,
    this.showAvatar = true,
    this.showMeta = true,
    this.onRetry,
    this.onLongPress,
    this.quoted,
    this.quotedSender,
    this.botAvatarUrl,
  });

  bool get _isCarousel {
    if (message.messageType == 'flex') {
      final flexData = (message.content is Map && message.content['contents'] != null)
          ? message.content['contents']
          : message.content;
      return flexData is Map && flexData['type'] == 'carousel';
    }
    if (message.messageType == 'template') {
      final templateData = (message.content is Map && message.content['template'] != null)
          ? message.content['template']
          : message.content;
      return templateData is Map && templateData['type'] == 'carousel';
    }
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final isUser = message.isUser;
    final isCarousel = _isCarousel;
    final palette = ChatPalette.of(context);

    final built = _buildContent(context, isUser, palette);
    final content = onLongPress == null
        ? built
        : GestureDetector(onLongPress: onLongPress, child: built);

    final column = Column(
      crossAxisAlignment: isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        content,
        if (showMeta || message.status == 'failed')
          Padding(
            padding: const EdgeInsets.only(top: 3, left: 4, right: 4),
            child: _buildMeta(context, isUser, palette),
          ),
      ],
    );

    return Padding(
      padding: EdgeInsets.only(
        left: 12,
        right: isCarousel && !isUser ? 0 : 12,
        top: showAvatar && !isUser ? 10 : 2,
        bottom: showMeta ? 6 : 1,
      ),
      child: Row(
        mainAxisAlignment: isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isUser) ...[
            showAvatar
                ? BotAvatar(size: _avatarSize, url: botAvatarUrl)
                : const SizedBox(width: _avatarSize),
            const SizedBox(width: _avatarGap),
          ],
          if (isUser) const SizedBox(width: 48),
          Flexible(child: column),
          if (!isUser && !isCarousel) const SizedBox(width: 48),
        ],
      ),
    );
  }

  Widget _buildMeta(BuildContext context, bool isUser, ChatPalette palette) {
    final timeStr = DateFormat('HH:mm').format(message.timestamp);
    final metaStyle = TextStyle(fontSize: 11, color: palette.meta);

    if (isUser && message.status == 'failed') {
      final errorColor = Theme.of(context).colorScheme.error;
      return InkWell(
        onTap: onRetry,
        borderRadius: BorderRadius.circular(6),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline_rounded, size: 14, color: errorColor),
            const SizedBox(width: 4),
            Text(
              onRetry != null ? '傳送失敗，點此重試' : '傳送失敗',
              style: TextStyle(fontSize: 11, color: errorColor),
            ),
          ],
        ),
      );
    }

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(timeStr, style: metaStyle),
        if (isUser) ...[
          const SizedBox(width: 4),
          Icon(
            message.status == 'sending' ? Icons.schedule_rounded : Icons.done_rounded,
            size: 13,
            color: palette.meta,
          ),
        ],
      ],
    );
  }

  Widget _buildContent(BuildContext context, bool isUser, ChatPalette palette) {
    final Widget inner;
    switch (message.messageType) {
      case 'text':
        inner = _buildTextBubble(context, isUser, palette);
        break;
      case 'image':
        inner = _buildImageBubble(context, isUser);
        break;
      case 'audio':
        inner = _buildAudioBubble(isUser, palette);
        break;
      case 'sticker':
        inner = _buildStickerBubble(context);
        break;
      case 'location':
        inner = _buildLocationBubble(context, palette);
        break;
      case 'template':
        inner = _buildTemplateBubble();
        break;
      case 'flex':
        inner = _buildFlexBubble();
        break;
      case 'video':
        inner = VideoMessageBubble(message: message);
        break;
      case 'file':
        inner = FileMessageBubble(
          message: message,
          isUser: isUser,
          onAction: onAction,
          borderRadius: _bubbleRadius(isUser),
        );
        break;
      case 'imagemap':
        inner = message.content is Map
            ? ImagemapMessageWidget(
                data: Map<String, dynamic>.from(message.content as Map),
                onAction: onAction,
              )
            : _buildUnsupportedBubble(context, isUser, palette);
        break;
      default:
        inner = _buildUnsupportedBubble(context, isUser, palette);
    }
    return inner;
  }

  BorderRadius _bubbleRadius(bool isUser) {
    const r = Radius.circular(18);
    const tail = Radius.circular(6);
    return BorderRadius.only(
      topLeft: !isUser && showAvatar ? tail : r,
      topRight: isUser ? tail : r,
      bottomLeft: r,
      bottomRight: r,
    );
  }

  Widget _buildTextBubble(BuildContext context, bool isUser, ChatPalette palette) {
    final bg = isUser ? palette.userBubble : palette.botBubble;
    final fg = isUser ? palette.onUserBubble : palette.onBotBubble;

    return Container(
      constraints: const BoxConstraints(maxWidth: 300),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: _bubbleRadius(isUser),
        border: isUser ? null : Border.all(color: palette.botBubbleBorder),
      ),
      child: message.quotedMessageId == null
          ? Text(message.text, style: TextStyle(color: fg, fontSize: 15, height: 1.4))
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                _buildQuote(fg),
                const SizedBox(height: 6),
                Text(message.text, style: TextStyle(color: fg, fontSize: 15, height: 1.4)),
              ],
            ),
    );
  }

  /// 回覆訊息上方的引用框：發送者 + 原訊息摘要
  Widget _buildQuote(Color fg) {
    final q = quoted;
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: Container(
        color: fg.withValues(alpha: 0.08),
        child: IntrinsicHeight(
          child: Row(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(width: 3, color: fg.withValues(alpha: 0.45)),
              Flexible(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(8, 5, 10, 5),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        q == null ? '原訊息' : (quotedSender ?? ''),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(color: fg, fontSize: 12, fontWeight: FontWeight.w700),
                      ),
                      Text(
                        q == null ? '這則訊息已不在這支手機上' : q.summary,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(color: fg.withValues(alpha: 0.75), fontSize: 12.5, height: 1.3),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildUnsupportedBubble(BuildContext context, bool isUser, ChatPalette palette) {
    final text = message.text;
    final url = message.mediaUrl;
    final label = switch (message.messageType) {
      'video' => '影片訊息',
      'file' => '檔案訊息',
      'imagemap' => '圖片地圖訊息',
      _ => '${message.messageType} 訊息',
    };

    return Container(
      constraints: const BoxConstraints(maxWidth: 300),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: palette.botBubble,
        borderRadius: _bubbleRadius(isUser),
        border: Border.all(color: palette.botBubbleBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.info_outline_rounded, size: 16, color: palette.meta),
              const SizedBox(width: 6),
              Text(label, style: TextStyle(fontSize: 13, color: palette.meta)),
            ],
          ),
          if (text.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(text, style: TextStyle(color: palette.onBotBubble, fontSize: 15)),
          ],
          if (url != null && url.isNotEmpty) ...[
            const SizedBox(height: 4),
            SelectableText(
              url,
              style: TextStyle(color: Theme.of(context).colorScheme.primary, fontSize: 13),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildImageBubble(BuildContext context, bool isUser) {
    final url = message.mediaUrl ?? '';
    final isLocal = url.startsWith('/') || url.startsWith('file://');
    final scheme = Theme.of(context).colorScheme;

    Widget imageWidget;
    if (isLocal) {
      final file = File(url.replaceFirst('file://', ''));
      imageWidget = Image.file(file, fit: BoxFit.cover);
    } else if (url.isNotEmpty) {
      imageWidget = CachedNetworkImage(
        imageUrl: url,
        fit: BoxFit.cover,
        placeholder: (_, __) => Container(
          width: 220,
          height: 180,
          color: scheme.surfaceContainerHighest,
          child: const Center(child: CircularProgressIndicator(strokeWidth: 2)),
        ),
        errorWidget: (_, __, ___) => Container(
          width: 220,
          height: 180,
          color: scheme.surfaceContainerHighest,
          child: Icon(Icons.broken_image_outlined, color: scheme.outline),
        ),
      );
    } else {
      imageWidget = const SizedBox.shrink();
    }

    return GestureDetector(
      onTap: () {
        if (url.isNotEmpty) {
          _showFullScreenImage(context, url, isLocal);
        }
      },
      child: Container(
        constraints: const BoxConstraints(maxWidth: 240, maxHeight: 300),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.5)),
        ),
        clipBehavior: Clip.antiAlias,
        child: imageWidget,
      ),
    );
  }

  void _showFullScreenImage(BuildContext context, String url, bool isLocal) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => Scaffold(
          backgroundColor: Colors.black,
          appBar: AppBar(
            backgroundColor: Colors.black,
            foregroundColor: Colors.white,
          ),
          body: Center(
            child: InteractiveViewer(
              child: isLocal
                  ? Image.file(File(url.replaceFirst('file://', '')))
                  : CachedNetworkImage(imageUrl: url),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildAudioBubble(bool isUser, ChatPalette palette) {
    final url = message.mediaUrl ?? '';

    return Container(
      decoration: BoxDecoration(
        color: isUser ? palette.userBubble : palette.botBubble,
        borderRadius: _bubbleRadius(isUser),
        border: isUser ? null : Border.all(color: palette.botBubbleBorder),
      ),
      child: AudioPlayerWidget(
        audioUrl: url,
        durationMs: message.duration,
        isUser: isUser,
      ),
    );
  }

  Widget _buildStickerBubble(BuildContext context) {
    final content = message.content is Map ? message.content as Map : {};
    final pkgId = content['packageId']?.toString() ?? '1';
    final stickerId = content['stickerId']?.toString() ?? '1';
    final baseUrl = AuthService().serverUrl.replaceAll(RegExp(r'/+$'), '');
    final stickerUrl = '$baseUrl/stickers/$pkgId/$stickerId';

    return Container(
      constraints: const BoxConstraints(maxWidth: 130, maxHeight: 130),
      padding: const EdgeInsets.all(2),
      child: CachedNetworkImage(
        imageUrl: stickerUrl,
        fit: BoxFit.contain,
        placeholder: (_, __) => const SizedBox(
          width: 80,
          height: 80,
          child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
        ),
        errorWidget: (_, __, ___) => const Center(
          child: Text('😊', style: TextStyle(fontSize: 60)),
        ),
      ),
    );
  }

  Widget _buildTemplateBubble() {
    final templateData = (message.content is Map && message.content['template'] != null)
        ? Map<String, dynamic>.from(message.content['template'])
        : (message.content is Map ? Map<String, dynamic>.from(message.content) : <String, dynamic>{});

    return TemplateMessageWidget(
      templateData: templateData,
      onAction: onAction,
    );
  }

  Widget _buildFlexBubble() {
    final flexData = (message.content is Map && message.content['contents'] != null)
        ? Map<String, dynamic>.from(message.content['contents'])
        : (message.content is Map ? Map<String, dynamic>.from(message.content) : <String, dynamic>{});

    return FlexMessageWidget(
      flexContents: flexData,
      onAction: onAction,
    );
  }

  Widget _buildLocationBubble(BuildContext context, ChatPalette palette) {
    final scheme = Theme.of(context).colorScheme;
    final title = message.locationTitle;
    final address = message.locationAddress;
    final lat = message.latitude.toStringAsFixed(5);
    final lng = message.longitude.toStringAsFixed(5);

    return Container(
      width: 260,
      decoration: BoxDecoration(
        color: palette.botBubble,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: palette.botBubbleBorder),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            height: 84,
            width: double.infinity,
            color: scheme.primaryContainer,
            child: Stack(
              alignment: Alignment.center,
              children: [
                Positioned(
                  right: -12,
                  bottom: -18,
                  child: Icon(
                    Icons.map_outlined,
                    size: 110,
                    color: scheme.onPrimaryContainer.withValues(alpha: 0.12),
                  ),
                ),
                CircleAvatar(
                  radius: 20,
                  backgroundColor: scheme.primary,
                  child: Icon(Icons.place_rounded, color: scheme.onPrimary, size: 22),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: palette.onBotBubble,
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                if (address.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(
                    address,
                    style: TextStyle(fontSize: 12.5, color: palette.meta, height: 1.35),
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
                const SizedBox(height: 8),
                Text(
                  '$lat, $lng',
                  style: TextStyle(
                    fontSize: 11,
                    color: palette.meta,
                    fontFamily: 'monospace',
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
