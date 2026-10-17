import 'package:flutter/material.dart';
import '../models/bot_info.dart';
import '../services/auth_service.dart';
import '../services/chat_hub.dart';
import '../services/database_service.dart';
import '../widgets/bot_avatar.dart';

/// 設定畫面關閉時回傳的結果，讓聊天室知道要做什麼。
enum BotSettingsResult { none, clearedHistory, left }

/// 單一 Bot 的設定：封鎖、清除本機紀錄、刪除好友。
class BotSettingsScreen extends StatefulWidget {
  final BotInfo bot;

  const BotSettingsScreen({super.key, required this.bot});

  @override
  State<BotSettingsScreen> createState() => _BotSettingsScreenState();
}

class _BotSettingsScreenState extends State<BotSettingsScreen> {
  final AuthService _auth = AuthService();
  final DatabaseService _db = DatabaseService();
  final ChatHub _hub = ChatHub();

  bool _busy = false;
  BotSettingsResult _result = BotSettingsResult.none;

  BotInfo get _bot => _auth.botById(widget.bot.botId) ?? widget.bot;

  void _snack(String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<bool> _confirm({
    required String title,
    required String message,
    required String okLabel,
    bool danger = false,
  }) async {
    final scheme = Theme.of(context).colorScheme;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: danger
                ? FilledButton.styleFrom(
                    backgroundColor: scheme.error,
                    foregroundColor: scheme.onError,
                  )
                : null,
            child: Text(okLabel),
          ),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _toggleBlocked(bool block) async {
    if (block &&
        !await _confirm(
          title: '封鎖「${_bot.name}」？',
          message: '封鎖後將收不到這個 Bot 的任何訊息，也無法傳訊息給它。之後可以隨時解除封鎖。',
          okLabel: '封鎖',
        )) {
      return;
    }
    setState(() => _busy = true);
    final ok = await _auth.setBlocked(_bot.botId, block);
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) await _hub.reload();
    _snack(ok ? (block ? '已封鎖 ${_bot.name}' : '已解除封鎖') : '無法連線到伺服器，請稍後再試');
  }

  Future<void> _clearHistory() async {
    if (!await _confirm(
      title: '清除本機對話紀錄',
      message: '確定要清除這支手機上與「${_bot.name}」的對話紀錄嗎？伺服器上的紀錄不受影響。',
      okLabel: '清除',
      danger: true,
    )) {
      return;
    }
    await _db.clear(botId: _bot.botId);
    _result = BotSettingsResult.clearedHistory;
    if (mounted) _snack('本機紀錄已清除');
  }

  Future<void> _leave() async {
    final name = _bot.name;
    if (!await _confirm(
      title: '刪除「$name」？',
      message: '會通知 Bot 你已離開，並清除伺服器與這支手機上你和它之間的所有對話。之後要再加入需要新的邀請碼。',
      okLabel: '刪除',
      danger: true,
    )) {
      return;
    }
    setState(() => _busy = true);
    final botId = _bot.botId;
    final ok = await _auth.leave(botId);
    if (!mounted) return;
    setState(() => _busy = false);
    if (!ok) {
      _snack('無法連線到伺服器，請稍後再試');
      return;
    }
    await _hub.removeBotLocally(botId);
    if (!mounted) return;
    Navigator.pop(context, BotSettingsResult.left);
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final bot = _bot;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) Navigator.pop(context, _result);
      },
      child: Scaffold(
        appBar: AppBar(title: const Text('Bot 設定')),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
          children: [
            Container(
              decoration: BoxDecoration(
                color: scheme.surfaceContainerLow,
                borderRadius: BorderRadius.circular(16),
              ),
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  BotAvatar(size: 52, url: bot.avatarUrl),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(bot.name, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                        if (bot.description.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 2),
                            child: Text(
                              bot.description,
                              style: TextStyle(fontSize: 13, color: scheme.onSurfaceVariant),
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            Container(
              decoration: BoxDecoration(
                color: scheme.surfaceContainerLow,
                borderRadius: BorderRadius.circular(16),
              ),
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(
                children: [
                  SwitchListTile(
                    secondary: const Icon(Icons.block_rounded),
                    title: const Text('封鎖這個 Bot'),
                    subtitle: const Text('封鎖後不會再收到它的訊息'),
                    value: bot.blocked,
                    onChanged: _busy ? null : _toggleBlocked,
                  ),
                  const Divider(indent: 16, endIndent: 16),
                  ListTile(
                    leading: Icon(Icons.delete_outline_rounded, color: scheme.error),
                    title: Text('清除本機對話紀錄', style: TextStyle(color: scheme.error)),
                    onTap: _busy ? null : _clearHistory,
                  ),
                  const Divider(indent: 16, endIndent: 16),
                  ListTile(
                    leading: Icon(Icons.person_remove_outlined, color: scheme.error),
                    title: Text('刪除好友', style: TextStyle(color: scheme.error)),
                    subtitle: const Text('離開這個 Bot 並清除所有對話'),
                    onTap: _busy ? null : _leave,
                  ),
                ],
              ),
            ),
            if (_busy) const Padding(padding: EdgeInsets.only(top: 24), child: LinearProgressIndicator()),
          ],
        ),
      ),
    );
  }
}
