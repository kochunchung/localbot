import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../config.dart';
import '../services/auth_service.dart';
import '../services/chat_hub.dart';
import '../widgets/bot_avatar.dart';

/// 全域設定（所有 Bot 共用）：伺服器網址、顯示名稱、這支手機的金鑰狀態、重設。
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final AuthService _auth = AuthService();
  final ChatHub _hub = ChatHub();

  late TextEditingController _urlController;
  late TextEditingController _nameController;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: _auth.serverUrl);
    _nameController = TextEditingController(text: _auth.displayName);
  }

  @override
  void dispose() {
    _urlController.dispose();
    _nameController.dispose();
    super.dispose();
  }

  void _snack(String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _save() async {
    final url = AuthService.normalizeServerUrl(_urlController.text);
    if (url == null) {
      _snack('伺服器網址需以 https:// 開頭');
      return;
    }
    final name = _nameController.text.trim();
    if (name.isEmpty) {
      _snack('顯示名稱不可空白');
      return;
    }
    setState(() => _saving = true);
    final urlChanged = url != _auth.baseUrl;
    await _auth.updateServerUrl(url);
    final nameOk = await _auth.updateDisplayName(name);
    // 網址改了就重新連線並同步 Bot 清單
    if (urlChanged) await _hub.start();
    if (!mounted) return;
    setState(() => _saving = false);
    _snack(nameOk ? '已儲存' : '已儲存在這支手機，但無法同步到伺服器，請確認網址與網路');
  }

  Future<bool> _confirm(String title, String message, String okLabel) async {
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
            style: FilledButton.styleFrom(
              backgroundColor: scheme.error,
              foregroundColor: scheme.onError,
            ),
            child: Text(okLabel),
          ),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _clearAllHistory() async {
    if (!await _confirm('清除所有本機對話紀錄', '確定要清除這支手機上所有 Bot 的對話紀錄嗎？伺服器上的紀錄不受影響。', '清除')) {
      return;
    }
    await _hub.wipeLocalData();
    if (mounted) _snack('本機紀錄已清除');
  }

  Future<void> _resetIdentity() async {
    if (!await _confirm(
      '重設這支手機',
      '會清除這支手機上的金鑰、Bot 清單與所有對話紀錄，並換成新的使用者 ID。'
          '之後需要新的邀請碼才能再加入。伺服器上原本的好友紀錄不會被刪除（可請管理員在後台處理）。',
      '重設',
    )) {
      return;
    }
    await _hub.stop();
    await _hub.wipeLocalData();
    await _auth.resetIdentity();
    if (!mounted) return;
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  Widget _sectionTitle(String text) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 20, 4, 8),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w700,
          color: scheme.primary,
          letterSpacing: 0.3,
        ),
      ),
    );
  }

  Widget _card({required List<Widget> children, EdgeInsets? padding}) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(16),
      ),
      padding: padding ?? const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(title: const Text('設定')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
        children: [
          _sectionTitle('伺服器與個人化'),
          _card(
            children: [
              TextField(
                controller: _urlController,
                keyboardType: TextInputType.url,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: '伺服器網址',
                  hintText: 'https://your-domain.example.com',
                  helperText: '網域有變動時在這裡更新；換成另一台伺服器請用新的邀請碼加入',
                  helperMaxLines: 2,
                  border: OutlineInputBorder(),
                  prefixIcon: Icon(Icons.dns_outlined),
                ),
              ),
              const SizedBox(height: 14),
              TextField(
                controller: _nameController,
                decoration: const InputDecoration(
                  labelText: '我的顯示名稱',
                  helperText: '所有 Bot 看到的是同一個名稱（Bot 呼叫 get_profile 取得）',
                  helperMaxLines: 2,
                  border: OutlineInputBorder(),
                  prefixIcon: Icon(Icons.person_outline),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          SizedBox(
            height: 50,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
              ),
              onPressed: _saving ? null : _save,
              icon: _saving
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.check_rounded),
              label: const Text('儲存', style: TextStyle(fontSize: 16)),
            ),
          ),
          _sectionTitle('這支手機'),
          _card(
            padding: const EdgeInsets.symmetric(vertical: 4),
            children: [
              ListTile(
                leading: const Icon(Icons.fingerprint),
                title: const Text('User ID'),
                subtitle: Text(
                  _auth.userId,
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                ),
                trailing: IconButton(
                  icon: const Icon(Icons.copy_rounded, size: 20),
                  tooltip: '複製 User ID',
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: _auth.userId));
                    _snack('已複製 User ID');
                  },
                ),
              ),
              const Divider(indent: 16, endIndent: 16),
              ListTile(
                leading: Icon(
                  _auth.hasKey && !_auth.keyRevoked ? Icons.key_rounded : Icons.key_off_rounded,
                  color: _auth.hasKey && !_auth.keyRevoked ? null : scheme.error,
                ),
                title: const Text('專屬金鑰'),
                subtitle: Text(
                  !_auth.hasKey
                      ? '尚未加入任何 Bot'
                      : (_auth.keyRevoked ? '已失效，請用新的邀請碼重新加入' : '已設定（管理員可在後台單獨撤銷）'),
                ),
              ),
              const Divider(indent: 16, endIndent: 16),
              ListTile(
                leading: Icon(Icons.delete_outline_rounded, color: scheme.error),
                title: Text('清除所有本機對話紀錄', style: TextStyle(color: scheme.error)),
                onTap: _clearAllHistory,
              ),
              const Divider(indent: 16, endIndent: 16),
              ListTile(
                leading: Icon(Icons.restart_alt_rounded, color: scheme.error),
                title: Text('重設這支手機', style: TextStyle(color: scheme.error)),
                subtitle: const Text('清除金鑰與 Bot 清單，換新的使用者 ID'),
                onTap: _resetIdentity,
              ),
            ],
          ),
          _sectionTitle('關於'),
          _card(
            children: [
              Row(
                children: [
                  const BotAvatar(size: 44),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'LocalBot',
                          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                        ),
                        Text(
                          '版本 ${AppConfig.appVersion} · MIT License',
                          style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                'LocalBot 是開源的自架聊天機器人用戶端，相容 Messaging API 格式。'
                '本專案為獨立專案，與 LINE Corporation / LY Corporation 無任何關係。',
                style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant, height: 1.5),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
