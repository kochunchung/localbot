import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:localbot_app/models/message.dart';
import 'package:localbot_app/theme/app_theme.dart';
import 'package:localbot_app/widgets/chat_bubble.dart';

Widget _wrap(Widget child) => MaterialApp(
      theme: AppTheme.light(),
      home: Scaffold(body: SingleChildScrollView(child: child)),
    );

void main() {
  testWidgets('文字訊息泡泡會顯示內容', (tester) async {
    final msg = ChatMessage(
      id: 'm1',
      userId: 'u1',
      isUser: false,
      messageType: 'text',
      content: {'type': 'text', 'text': '哈囉，我是 Bot'},
      timestamp: DateTime(2026, 1, 1, 9, 30),
    );
    await tester.pumpWidget(_wrap(ChatBubble(message: msg, onAction: (_) {})));
    expect(find.text('哈囉，我是 Bot'), findsOneWidget);
    expect(find.text('09:30'), findsOneWidget);
  });

  testWidgets('Confirm 模板按鈕會回傳對應的 action', (tester) async {
    Map<String, dynamic>? tapped;
    final msg = ChatMessage(
      id: 'm2',
      userId: 'u1',
      isUser: false,
      messageType: 'template',
      content: {
        'type': 'template',
        'altText': '確認',
        'template': {
          'type': 'confirm',
          'text': '要設定提醒嗎？',
          'actions': [
            {'type': 'postback', 'label': '好', 'data': 'yes'},
            {'type': 'postback', 'label': '不用', 'data': 'no'},
          ],
        },
      },
      timestamp: DateTime(2026, 1, 1, 9, 31),
    );
    await tester.pumpWidget(_wrap(ChatBubble(message: msg, onAction: (a) => tapped = a)));
    expect(find.text('要設定提醒嗎？'), findsOneWidget);
    await tester.tap(find.text('好'));
    expect(tapped?['data'], 'yes');
  });
}
