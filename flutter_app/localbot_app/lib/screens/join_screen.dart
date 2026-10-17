import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../config.dart';
import '../models/bot_info.dart';
import '../models/join_link.dart';
import '../services/auth_service.dart';
import '../services/chat_hub.dart';
import '../widgets/bot_avatar.dart';
import 'qr_scan_screen.dart';

/// 用管理員給的邀請碼（或邀請連結 / QR Code）加入 Bot。
///
/// 第一次加入時，伺服器會發一把這支手機專屬的金鑰；之後再加入其他 Bot 不需要再設定。
class JoinScreen extends StatefulWidget {
  /// 從連結或 QR Code 帶進來的邀請（會預先填好欄位，仍需按「加入」確認）
  final JoinInvite? initialInvite;

  /// 金鑰被撤銷後重新加入
  final bool revoked;

  /// 從 Bot 清單進來（可以返回）；第一次加入時是整個 App 的首頁
  final bool canCancel;

  const JoinScreen({
    super.key,
    this.initialInvite,
    this.revoked = false,
    this.canCancel = false,
  });

  @override
  State<JoinScreen> createState() => _JoinScreenState();
}

class _JoinScreenState extends State<JoinScreen> {
  final AuthService _auth = AuthService();
  final ChatHub _hub = ChatHub();

  late final TextEditingController _serverController;
  late final TextEditingController _codeController;
  late final TextEditingController _nameController;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _serverController = TextEditingController(
      text: _auth.serverUrl.isNotEmpty ? _auth.serverUrl : AppConfig.defaultServerUrl,
    );
    _codeController = TextEditingController();
    _nameController = TextEditingController(
      text: _auth.displayName == 'User' ? '' : _auth.displayName,
    );
    final invite = widget.initialInvite;
    if (invite != null) _applyInvite(invite);
  }

  @override
  void dispose() {
    _serverController.dispose();
    _codeController.dispose();
    _nameController.dispose();
    super.dispose();
  }

  void _applyInvite(JoinInvite invite) {
    _codeController.text = invite.code;
    if (invite.serverUrl != null) _serverController.text = invite.serverUrl!;
  }

  Future<void> _scan() async {
    final raw = await Navigator.push<String>(
      context,
      MaterialPageRoute(builder: (_) => const QrScanScreen()),
    );
    if (raw == null || !mounted) return;
    final invite = JoinInvite.parse(raw);
    if (invite == null) return;
    setState(() {
      _error = null;
      _applyInvite(invite);
    });
  }

  Future<void> _paste() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    final invite = JoinInvite.parse(data?.text ?? '');
    if (!mounted) return;
    if (invite == null) {
      setState(() => _error = '剪貼簿裡沒有邀請碼或邀請連結');
      return;
    }
    setState(() {
      _error = null;
      _applyInvite(invite);
    });
  }

  Future<void> _join() async {
    final code = JoinInvite.normalizeCode(_codeController.text);
    if (code.isEmpty) {
      setState(() => _error = '請輸入邀請碼');
      return;
    }
    final server = AuthService.normalizeServerUrl(_serverController.text);
    if (server == null) {
      setState(() => _error = '伺服器網址需以 https:// 開頭');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final result = await _auth.join(
      serverUrl: server,
      code: code,
      displayName: _nameController.text,
    );
    if (!mounted) return;
    if (!result.ok) {
      setState(() {
        _busy = false;
        _error = result.message;
      });
      return;
    }
    if (result.serverChanged) await _hub.wipeLocalData();
    await _hub.start();
    if (!mounted) return;
    setState(() => _busy = false);
    final bot = result.bot;
    if (Navigator.of(context).canPop()) Navigator.pop<BotInfo?>(context, bot);
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.canCancel ? '加入 Bot' : 'LocalBot'),
        automaticallyImplyLeading: widget.canCancel,
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
          children: [
            const Center(child: BotAvatar(size: 72)),
            const SizedBox(height: 16),
            Text(
              widget.revoked ? '請重新加入' : '加入你的 Bot',
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            Text(
              widget.revoked
                  ? '這支手機的金鑰已被管理員撤銷或失效。請向管理員索取新的邀請碼重新加入，原本的對話紀錄仍會保留。'
                  : '向伺服器管理員索取邀請碼（或 QR Code），就能加入 Bot 開始聊天。一位使用者可以加入多個 Bot。',
              textAlign: TextAlign.center,
              style: TextStyle(color: scheme.onSurfaceVariant, height: 1.5),
            ),
            if (widget.revoked) ...[
              const SizedBox(height: 16),
              Material(
                color: scheme.errorContainer,
                borderRadius: BorderRadius.circular(12),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Row(
                    children: [
                      Icon(Icons.key_off_rounded, color: scheme.onErrorContainer),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          '伺服器拒絕了這支手機的金鑰',
                          style: TextStyle(color: scheme.onErrorContainer),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
            const SizedBox(height: 24),
            FilledButton.tonalIcon(
              onPressed: _busy ? null : _scan,
              icon: const Icon(Icons.qr_code_scanner_rounded),
              label: const Text('掃描邀請 QR Code'),
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
            ),
            const SizedBox(height: 20),
            TextField(
              controller: _codeController,
              enabled: !_busy,
              autocorrect: false,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                labelText: '邀請碼',
                hintText: 'XXXXX-XXXXX',
                border: const OutlineInputBorder(),
                prefixIcon: const Icon(Icons.confirmation_number_outlined),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.content_paste_rounded),
                  tooltip: '貼上',
                  onPressed: _busy ? null : _paste,
                ),
              ),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _serverController,
              enabled: !_busy,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: '伺服器網址',
                hintText: 'https://your-domain.example.com',
                helperText: '掃描 QR Code 或貼上邀請連結時會自動填入',
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.dns_outlined),
              ),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _nameController,
              enabled: !_busy,
              decoration: const InputDecoration(
                labelText: '我的顯示名稱',
                helperText: 'Bot 取得的使用者名稱（可留空）',
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.person_outline),
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 14),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.error_outline_rounded, size: 18, color: scheme.error),
                  const SizedBox(width: 8),
                  Expanded(child: Text(_error!, style: TextStyle(color: scheme.error))),
                ],
              ),
            ],
            const SizedBox(height: 20),
            SizedBox(
              height: 50,
              child: FilledButton.icon(
                style: FilledButton.styleFrom(
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                ),
                onPressed: _busy ? null : _join,
                icon: _busy
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.login_rounded),
                label: const Text('加入', style: TextStyle(fontSize: 16)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
