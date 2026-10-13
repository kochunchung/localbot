import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../config.dart';
import '../services/auth_service.dart';
import '../services/database_service.dart';
import '../services/socket_service.dart';
import '../widgets/bot_avatar.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final AuthService _auth = AuthService();
  final DatabaseService _db = DatabaseService();
  final SocketService _socket = SocketService();

  late TextEditingController _urlController;
  late TextEditingController _secretController;
  late TextEditingController _nameController;
  late TextEditingController _botNameController;
  bool _saving = false;
  bool _showSecret = false;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: _auth.serverUrl);
    _secretController = TextEditingController(text: _auth.channelSecret);
    _nameController = TextEditingController(text: _auth.displayName);
    _botNameController = TextEditingController(text: _auth.botName);
  }

  @override
  void dispose() {
    _urlController.dispose();
    _secretController.dispose();
    _nameController.dispose();
    _botNameController.dispose();
    super.dispose();
  }

  Future<void> _saveSettings() async {
    final url = _urlController.text.trim();
    if (!url.startsWith('https://')) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('伺服器網址需以 https:// 開頭')),
      );
      return;
    }

    setState(() => _saving = true);
    await _auth.updateSettings(
      serverUrl: url,
      channelSecret: _secretController.text.trim(),
      displayName: _nameController.text.trim(),
      botName: _botNameController.text.trim(),
    );

    // Re-register & reconnect socket
    final ok = await _auth.registerWithServer();
    _socket.connect();

    if (!mounted) return;
    setState(() => _saving = false);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(ok ? '已儲存並連線成功' : '已儲存，但無法向伺服器註冊，請確認網址與 App Secret'),
      ),
    );
    if (ok) Navigator.pop(context, true);
  }

  Future<void> _clearHistory() async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('清除對話紀錄'),
        content: const Text('確定要清除這支手機上的所有對話紀錄嗎？伺服器上的紀錄不受影響。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(ctx).colorScheme.error,
              foregroundColor: Theme.of(ctx).colorScheme.onError,
            ),
            child: const Text('清除'),
          ),
        ],
      ),
    );

    if (confirm == true) {
      await _db.clearAll();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('本機紀錄已清除')),
        );
      }
    }
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
          _sectionTitle('伺服器連線'),
          _card(
            children: [
              TextField(
                controller: _urlController,
                keyboardType: TextInputType.url,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: '伺服器網址',
                  hintText: 'https://your-domain.example.com',
                  border: OutlineInputBorder(),
                  prefixIcon: Icon(Icons.dns_outlined),
                ),
              ),
              const SizedBox(height: 14),
              TextField(
                controller: _secretController,
                obscureText: !_showSecret,
                autocorrect: false,
                decoration: InputDecoration(
                  labelText: 'App Secret',
                  helperText: '向伺服器管理者索取（LOCALBOT_APP_SECRET）',
                  border: const OutlineInputBorder(),
                  prefixIcon: const Icon(Icons.key_outlined),
                  suffixIcon: IconButton(
                    icon: Icon(_showSecret ? Icons.visibility_off_outlined : Icons.visibility_outlined),
                    tooltip: _showSecret ? '隱藏' : '顯示',
                    onPressed: () => setState(() => _showSecret = !_showSecret),
                  ),
                ),
              ),
            ],
          ),
          _sectionTitle('個人化'),
          _card(
            children: [
              TextField(
                controller: _nameController,
                decoration: const InputDecoration(
                  labelText: '我的顯示名稱',
                  helperText: 'Bot 呼叫 get_profile 時取得的名稱',
                  border: OutlineInputBorder(),
                  prefixIcon: Icon(Icons.person_outline),
                ),
              ),
              const SizedBox(height: 14),
              TextField(
                controller: _botNameController,
                decoration: const InputDecoration(
                  labelText: '聊天室標題（Bot 名稱）',
                  border: OutlineInputBorder(),
                  prefixIcon: Icon(Icons.smart_toy_outlined),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          SizedBox(
            height: 50,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
              ),
              onPressed: _saving ? null : _saveSettings,
              icon: _saving
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.check_rounded),
              label: const Text('儲存並重新連線', style: TextStyle(fontSize: 16)),
            ),
          ),
          _sectionTitle('裝置'),
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
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('已複製 User ID')),
                    );
                  },
                ),
              ),
              const Divider(indent: 16, endIndent: 16),
              ListTile(
                leading: Icon(Icons.delete_outline_rounded, color: scheme.error),
                title: Text('清除本機對話紀錄', style: TextStyle(color: scheme.error)),
                onTap: _clearHistory,
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
