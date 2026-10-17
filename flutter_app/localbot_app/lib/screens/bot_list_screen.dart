import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../models/bot_info.dart';
import '../models/message.dart';
import '../services/chat_hub.dart';
import '../services/socket_service.dart';
import '../theme/app_theme.dart';
import '../widgets/bot_avatar.dart';
import 'chat_screen.dart';
import 'join_screen.dart';
import 'settings_screen.dart';

/// 已加入的 Bot 清單（像 LINE 的好友 / 聊天列表）。
class BotListScreen extends StatefulWidget {
  const BotListScreen({super.key});

  @override
  State<BotListScreen> createState() => _BotListScreenState();
}

class _BotListScreenState extends State<BotListScreen> {
  final ChatHub _hub = ChatHub();

  @override
  void initState() {
    super.initState();
    _hub.addListener(_onHubChanged);
    _hub.refresh();
  }

  @override
  void dispose() {
    _hub.removeListener(_onHubChanged);
    super.dispose();
  }

  void _onHubChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _openChat(BotInfo bot) async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => ChatScreen(bot: bot)),
    );
    if (!mounted) return;
    // 回到清單時，封鎖狀態、預覽、未讀數可能都變了
    await _hub.reload();
  }

  Future<void> _addBot() async {
    final bot = await Navigator.push<BotInfo?>(
      context,
      MaterialPageRoute(builder: (_) => const JoinScreen(canCancel: true)),
    );
    if (bot == null || !mounted) return;
    _openChat(bot);
  }

  Future<void> _openSettings() async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const SettingsScreen()),
    );
    if (mounted) setState(() {});
  }

  static String _preview(ChatMessage? m) {
    if (m == null) return '';
    final prefix = m.isUser ? '你：' : '';
    switch (m.messageType) {
      case 'text':
        final t = m.text.replaceAll('\n', ' ');
        return '$prefix$t';
      case 'image':
        return '$prefix[圖片]';
      case 'video':
        return '$prefix[影片]';
      case 'audio':
        return '$prefix[語音訊息]';
      case 'file':
        return '$prefix[檔案] ${m.fileName}';
      case 'sticker':
        return '$prefix[貼圖]';
      case 'location':
        return '$prefix[位置資訊]';
      case 'postback':
        return '';
      default:
        final alt = m.text;
        return alt.isNotEmpty ? '$prefix$alt' : '$prefix[訊息]';
    }
  }

  static String _timeLabel(DateTime t) {
    final now = DateTime.now();
    final sameDay = t.year == now.year && t.month == now.month && t.day == now.day;
    if (sameDay) return DateFormat('HH:mm').format(t);
    if (t.year == now.year) return DateFormat('M/d').format(t);
    return DateFormat('yyyy/M/d').format(t);
  }

  Widget _offlineBanner(ColorScheme scheme) {
    if (_hub.connectionState != SocketConnectionState.disconnected) {
      return const SizedBox.shrink();
    }
    return Material(
      color: scheme.errorContainer,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
        child: Row(
          children: [
            Icon(Icons.cloud_off_rounded, size: 18, color: scheme.onErrorContainer),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                '無法連線到伺服器，正在自動重試',
                style: TextStyle(fontSize: 13, color: scheme.onErrorContainer),
              ),
            ),
            TextButton(onPressed: _openSettings, child: const Text('檢查設定')),
          ],
        ),
      ),
    );
  }

  Widget _tile(BotInfo bot) {
    final scheme = Theme.of(context).colorScheme;
    final last = _hub.lastMessageOf(bot.botId);
    final unread = _hub.unreadFor(bot.botId);
    final subtitle = bot.blocked
        ? '已封鎖'
        : (last != null ? _preview(last) : (bot.description.isNotEmpty ? bot.description : '點一下開始聊天'));
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      leading: BotAvatar(size: 48, url: bot.avatarUrl),
      title: Text(
        bot.name,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(fontWeight: FontWeight.w700),
      ),
      subtitle: Text(
        subtitle,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(color: bot.blocked ? scheme.error : scheme.onSurfaceVariant),
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (last != null)
            Text(
              _timeLabel(last.timestamp),
              style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
            ),
          if (unread > 0) ...[
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
              decoration: BoxDecoration(
                color: AppTheme.statusOffline,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                unread > 99 ? '99+' : '$unread',
                style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700),
              ),
            ),
          ],
        ],
      ),
      onTap: () => _openChat(bot),
    );
  }

  Widget _emptyState(ColorScheme scheme) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(32),
      children: [
        const SizedBox(height: 48),
        const Center(child: BotAvatar(size: 72)),
        const SizedBox(height: 16),
        const Text(
          '還沒有加入任何 Bot',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 8),
        Text(
          '向管理員索取邀請碼或 QR Code 來加入。',
          textAlign: TextAlign.center,
          style: TextStyle(color: scheme.onSurfaceVariant),
        ),
        const SizedBox(height: 20),
        Center(
          child: FilledButton.icon(
            onPressed: _addBot,
            icon: const Icon(Icons.add_rounded),
            label: const Text('加入 Bot'),
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final bots = _hub.bots;
    return Scaffold(
      appBar: AppBar(
        title: const Text('LocalBot', style: TextStyle(fontWeight: FontWeight.w700)),
        actions: [
          IconButton(
            icon: const Icon(Icons.person_add_alt_1_rounded),
            tooltip: '加入 Bot',
            onPressed: _addBot,
          ),
          IconButton(
            icon: const Icon(Icons.tune_rounded),
            tooltip: '設定',
            onPressed: _openSettings,
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: Column(
        children: [
          _offlineBanner(scheme),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _hub.refresh,
              child: bots.isEmpty
                  ? _emptyState(scheme)
                  : ListView.separated(
                      physics: const AlwaysScrollableScrollPhysics(),
                      itemCount: bots.length,
                      separatorBuilder: (context, index) => const Divider(indent: 80),
                      itemBuilder: (context, index) => _tile(bots[index]),
                    ),
            ),
          ),
        ],
      ),
    );
  }
}
