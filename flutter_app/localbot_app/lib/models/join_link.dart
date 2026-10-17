/// 管理後台產生的邀請：邀請碼，加上（用連結 / QR Code 時）伺服器網址。
class JoinInvite {
  final String code;
  final String? serverUrl;

  const JoinInvite({required this.code, this.serverUrl});

  /// 邀請碼只留英數字並轉大寫（後台顯示成 XXXXX-XXXXX）。
  static String normalizeCode(String raw) =>
      raw.replaceAll(RegExp(r'[^A-Za-z0-9]'), '').toUpperCase();

  /// 解析使用者貼上 / 掃描到的文字。可以是
  ///   localbot://join?server=https%3A%2F%2Fexample.com&code=ABCDE23456
  /// 或單純的邀請碼（ABCDE-23456）。無法辨識時回傳 null。
  static JoinInvite? parse(String text) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return null;
    final uri = Uri.tryParse(trimmed);
    if (uri != null && uri.scheme.toLowerCase() == 'localbot') {
      if (uri.host.toLowerCase() != 'join') return null;
      final code = normalizeCode(uri.queryParameters['code'] ?? '');
      if (code.isEmpty) return null;
      final server = (uri.queryParameters['server'] ?? '').trim();
      return JoinInvite(code: code, serverUrl: server.isEmpty ? null : server);
    }
    if (trimmed.contains('://')) return null;
    final code = normalizeCode(trimmed);
    return code.length >= 6 ? JoinInvite(code: code) : null;
  }
}
