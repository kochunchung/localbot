import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:localbot_app/models/bot_info.dart';
import 'package:localbot_app/models/join_link.dart';
import 'package:localbot_app/models/message.dart';
import 'package:localbot_app/services/auth_service.dart';
import 'package:localbot_app/theme/app_theme.dart';
import 'package:localbot_app/widgets/chat_bubble.dart';
import 'package:localbot_app/widgets/flex_message_widget.dart';
import 'package:localbot_app/widgets/media_bubbles.dart';
import 'package:localbot_app/widgets/rich_menu_panel.dart';
import 'package:localbot_app/widgets/typing_indicator.dart';

Widget _wrap(Widget child) => MaterialApp(
      theme: AppTheme.light(),
      home: Scaffold(body: SingleChildScrollView(child: child)),
    );

void main() {
  testWidgets('文字訊息泡泡會顯示內容', (tester) async {
    final msg = ChatMessage(
      id: 'm1',
      botId: 'b1',
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
      botId: 'b1',
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

  test('ChatMessage 可解析 Quick Reply 與非標準型別欄位', () {
    final msg = ChatMessage.fromSocketPayload({
      'messageId': 'b1',
      'botId': 'shop',
      'userId': 'u1',
      'direction': 'outgoing',
      'messageType': 'text',
      'createdAt': 1791800000000,
      'content': {
        'type': 'text',
        'text': '要喝什麼？',
        'duration': 1.5,
        'quickReply': {
          'items': [
            {
              'type': 'action',
              'action': {'type': 'message', 'label': '咖啡', 'text': '咖啡'},
            },
            {
              'type': 'action',
              'action': {'type': 'datetimepicker', 'label': '預約', 'data': 'book', 'mode': 'date'},
            },
          ],
        },
      },
    });
    expect(msg.isUser, isFalse);
    expect(msg.botId, 'shop');
    expect(msg.quickReplyItems, hasLength(2));
    expect(msg.duration, 1);
    expect(msg.text, '要喝什麼？');
  });

  testWidgets('輸入中動畫可以正常繪製', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      home: const Scaffold(body: TypingIndicator()),
    ));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byType(TypingIndicator), findsOneWidget);
    expect(find.bySemanticsLabel('Bot 正在輸入'), findsOneWidget);
  });

  testWidgets('檔案訊息顯示檔名與大小，點擊會送出下載連結', (tester) async {
    Map<String, dynamic>? tapped;
    final msg = ChatMessage(
      id: 'f1',
      botId: 'b1',
      userId: 'u1',
      isUser: false,
      messageType: 'file',
      content: {
        'type': 'file',
        'originalContentUrl': 'https://example.com/media/report.pdf',
        'fileName': 'report.pdf',
        'fileSize': 2048,
      },
      timestamp: DateTime(2026, 1, 1, 10, 0),
    );
    await tester.pumpWidget(_wrap(ChatBubble(message: msg, onAction: (a) => tapped = a)));
    expect(find.text('report.pdf'), findsOneWidget);
    expect(find.text('2.0 KB  ·  點擊開啟'), findsOneWidget);
    await tester.tap(find.text('report.pdf'));
    expect(tapped, {'type': 'uri', 'uri': 'https://example.com/media/report.pdf'});
  });

  testWidgets('Imagemap 點擊區域會轉成對應動作', (tester) async {
    final tapped = <Map<String, dynamic>>[];
    await tester.pumpWidget(_wrap(ImagemapMessageWidget(
      data: {
        'type': 'imagemap',
        'baseUrl': '',
        'altText': 'map',
        'baseSize': {'width': 1040, 'height': 520},
        'actions': [
          {'type': 'message', 'text': '左邊', 'area': {'x': 0, 'y': 0, 'width': 520, 'height': 520}},
          {'type': 'uri', 'linkUri': 'https://example.com', 'area': {'x': 520, 'y': 0, 'width': 520, 'height': 520}},
        ],
      },
      onAction: tapped.add,
    )));
    final size = tester.getSize(find.byType(ImagemapMessageWidget));
    expect(size.width, ImagemapMessageWidget.displayWidth);
    expect(size.height, closeTo(ImagemapMessageWidget.displayWidth / 2, 0.01));
    final inkWells = find.byType(InkWell);
    expect(inkWells, findsNWidgets(2));
    await tester.tap(inkWells.at(0));
    await tester.tap(inkWells.at(1));
    expect(tapped[0], {'type': 'message', 'text': '左邊'});
    expect(tapped[1], {'type': 'uri', 'uri': 'https://example.com'});
  });

  test('formatFileSize', () {
    expect(formatFileSize(0), '');
    expect(formatFileSize(512), '512 B');
    expect(formatFileSize(1536), '1.5 KB');
    expect(formatFileSize(25 * 1024 * 1024), '25 MB');
  });

  group('Flex Message', () {
    final bubble = <String, dynamic>{
      'type': 'bubble',
      'size': 'kilo',
      'styles': {
        'footer': {'separator': true},
      },
      'header': {
        'type': 'box',
        'layout': 'vertical',
        'backgroundColor': '#4F46E5',
        'contents': [
          {'type': 'text', 'text': '訂單確認', 'color': '#FFFFFF', 'weight': 'bold', 'size': 'xl'},
        ],
      },
      'body': {
        'type': 'box',
        'layout': 'vertical',
        'spacing': 'md',
        'contents': [
          {
            'type': 'box',
            'layout': 'horizontal',
            'contents': [
              {'type': 'text', 'text': '品項', 'flex': 0, 'color': '#888888'},
              {'type': 'separator'},
              {'type': 'text', 'text': '拿鐵', 'align': 'end', 'gravity': 'center'},
            ],
          },
          {
            'type': 'box',
            'layout': 'baseline',
            'contents': [
              {'type': 'text', 'text': '金額', 'flex': 2},
              {'type': 'text', 'text': 'NT\$ 120', 'flex': 3, 'weight': 'bold'},
            ],
          },
          {
            'type': 'text',
            'wrap': true,
            'contents': [
              {'type': 'span', 'text': '提醒：'},
              {'type': 'span', 'text': '請於 10 分鐘內取餐', 'color': '#EF4444', 'decoration': 'underline'},
            ],
          },
          {
            'type': 'box',
            'layout': 'vertical',
            'height': '40px',
            'cornerRadius': 'md',
            'borderWidth': 'light',
            'borderColor': '#CCCCCC',
            'background': {
              'type': 'linearGradient',
              'angle': '90deg',
              'startColor': '#FFFFFF',
              'endColor': '#E0E7FF80',
            },
            'contents': [
              {'type': 'filler'},
              {'type': 'text', 'text': '漸層', 'align': 'center'},
              {'type': 'filler'},
            ],
          },
          {
            'type': 'box',
            'layout': 'vertical',
            'contents': [
              {'type': 'text', 'text': '底層'},
              {'type': 'text', 'text': 'NEW', 'position': 'absolute', 'offsetTop': '0px', 'offsetEnd': '0px'},
            ],
          },
        ],
      },
      'footer': {
        'type': 'box',
        'layout': 'horizontal',
        'spacing': 'sm',
        'contents': [
          {'type': 'button', 'style': 'secondary', 'height': 'sm', 'action': {'type': 'message', 'label': '取消', 'text': '取消'}},
          {'type': 'button', 'style': 'primary', 'height': 'sm', 'action': {'type': 'postback', 'label': '確認', 'data': 'ok=1'}},
        ],
      },
    };

    testWidgets('常用元件可以正常排版且按鈕有作用', (tester) async {
      Map<String, dynamic>? tapped;
      await tester.pumpWidget(_wrap(Align(
        alignment: Alignment.topLeft,
        child: FlexMessageWidget(flexContents: bubble, onAction: (a) => tapped = a),
      )));
      expect(tester.takeException(), isNull);
      expect(find.text('訂單確認'), findsOneWidget);
      expect(find.text('拿鐵'), findsOneWidget);
      expect(find.text('NEW'), findsOneWidget);
      expect(tester.getSize(find.byType(FlexMessageWidget)).width, lessThanOrEqualTo(260));
      await tester.tap(find.text('確認'));
      expect(tapped?['data'], 'ok=1');
    });

    testWidgets('輪播卡片可以水平排列', (tester) async {
      final carousel = {
        'type': 'carousel',
        'contents': [bubble, {...bubble, 'size': 'micro'}],
      };
      await tester.pumpWidget(_wrap(FlexMessageWidget(flexContents: carousel, onAction: (_) {})));
      expect(tester.takeException(), isNull);
      expect(find.text('訂單確認'), findsNWidgets(2));
    });

    test('顏色解析：#RRGGBBAA 的透明度在最後', () {
      expect(FlexRenderer.parseColor('#FF000080'), const Color(0x80FF0000));
      expect(FlexRenderer.parseColor('#00FF00'), const Color(0xFF00FF00));
      expect(FlexRenderer.parseColor('red'), isNull);
    });
  });

  testWidgets('Rich Menu 依比例顯示，點擊區域與標題列有作用', (tester) async {
    final tapped = <Map<String, dynamic>>[];
    var collapsed = false;
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      home: Scaffold(
        body: Align(
          alignment: Alignment.bottomCenter,
          child: SizedBox(
            width: 400,
            child: RichMenuPanel(
              menu: {
                'richMenuId': 'richmenu-1',
                'size': {'width': 2500, 'height': 843},
                'chatBarText': '主選單',
                'imageUrl': '',
                'areas': [
                  {
                    'bounds': {'x': 0, 'y': 0, 'width': 1250, 'height': 843},
                    'action': {'type': 'message', 'text': '左'},
                  },
                  {
                    'bounds': {'x': 1250, 'y': 0, 'width': 1250, 'height': 843},
                    'action': {'type': 'richmenuswitch', 'richMenuAliasId': 'page-2', 'data': 'p2'},
                  },
                ],
              },
              onAction: tapped.add,
              onCollapse: () => collapsed = true,
            ),
          ),
        ),
      ),
    ));
    expect(find.text('主選單'), findsOneWidget);
    final stack = tester.getSize(find.descendant(of: find.byType(RichMenuPanel), matching: find.byType(Stack)).first);
    expect(stack.width, 400);
    expect(stack.height, closeTo(400 * 843 / 2500, 0.01));

    final areas = find.descendant(of: find.byType(Positioned), matching: find.byType(InkWell));
    await tester.tap(areas.at(0));
    await tester.tap(areas.at(1));
    expect(tapped.map((a) => a['type']), ['message', 'richmenuswitch']);

    await tester.tap(find.text('主選單'));
    expect(collapsed, isTrue);
  });

  group('多 Bot', () {
    test('ChatMessage 存進資料庫再讀出來，botId 不會掉', () {
      final msg = ChatMessage(
        id: 'm9',
        botId: 'shop',
        userId: 'u1',
        isUser: true,
        messageType: 'text',
        content: {'text': 'hi'},
        timestamp: DateTime.fromMillisecondsSinceEpoch(1791800000000),
      );
      final map = msg.toMap();
      expect(map['bot_id'], 'shop');
      final back = ChatMessage.fromMap(map);
      expect(back.botId, 'shop');
      expect(back.text, 'hi');
    });

    test('BotInfo 轉成 JSON 再還原', () {
      final bot = BotInfo.fromJson({
        'botId': 'shop',
        'name': '商店 Bot',
        'description': '客服',
        'blocked': true,
        'lastMessageAt': 1791800000000,
        'avatarUrl': '/avatars/shop-1a2b3c4d.png',
      });
      expect(bot.name, '商店 Bot');
      expect(bot.blocked, isTrue);
      final again = BotInfo.fromJson(bot.toJson());
      expect(again.botId, 'shop');
      expect(again.lastMessageAt, 1791800000000);
      expect(again.avatarUrl, '/avatars/shop-1a2b3c4d.png');
      expect(bot.copyWith(blocked: false).blocked, isFalse);
      expect(bot.copyWith(blocked: false).avatarUrl, '/avatars/shop-1a2b3c4d.png');
      expect(BotInfo.fromJson({'botId': 'x', 'name': 'x'}).avatarUrl, '');
    });

    test('邀請連結：解析伺服器網址與邀請碼', () {
      final invite = JoinInvite.parse(
          'localbot://join?server=https%3A%2F%2Fbot.example.com&code=abcde23456');
      expect(invite, isNotNull);
      expect(invite!.code, 'ABCDE23456');
      expect(invite.serverUrl, 'https://bot.example.com');
    });

    test('邀請碼：接受含連字號與小寫的輸入', () {
      final invite = JoinInvite.parse(' abcde-23456 ');
      expect(invite?.code, 'ABCDE23456');
      expect(invite?.serverUrl, isNull);
    });

    test('邀請連結：無效內容回傳 null', () {
      expect(JoinInvite.parse(''), isNull);
      expect(JoinInvite.parse('abc'), isNull);
      expect(JoinInvite.parse('https://example.com/?code=ABCDE23456'), isNull);
      expect(JoinInvite.parse('localbot://other?code=ABCDE23456'), isNull);
      expect(JoinInvite.parse('localbot://join?server=x'), isNull);
    });

    test('伺服器網址只接受 https', () {
      expect(AuthService.normalizeServerUrl('https://bot.example.com/'), 'https://bot.example.com');
      expect(AuthService.normalizeServerUrl(' https://bot.example.com:8443 '), 'https://bot.example.com:8443');
      expect(AuthService.normalizeServerUrl('http://bot.example.com'), isNull);
      expect(AuthService.normalizeServerUrl('bot.example.com'), isNull);
      expect(AuthService.normalizeServerUrl(''), isNull);
    });
  });

  testWidgets('回覆訊息顯示引用框，長按會觸發選單', (tester) async {
    final original = ChatMessage(
      id: 'bot_1',
      botId: 'b1',
      userId: 'u1',
      isUser: false,
      messageType: 'image',
      content: {'originalContentUrl': 'https://example.com/a.jpg'},
      timestamp: DateTime(2026, 1, 1, 9, 0),
    );
    final reply = ChatMessage(
      id: 'msg_2',
      botId: 'b1',
      userId: 'u1',
      isUser: true,
      messageType: 'text',
      content: {'text': '這張不錯', 'quotedMessageId': 'bot_1'},
      timestamp: DateTime(2026, 1, 1, 9, 1),
    );
    expect(reply.quotedMessageId, 'bot_1');
    expect(original.summary, '[圖片]');

    var longPressed = 0;
    await tester.pumpWidget(_wrap(ChatBubble(
      message: reply,
      onAction: (_) {},
      quoted: original,
      quotedSender: '小幫手',
      onLongPress: () => longPressed++,
    )));
    expect(find.text('小幫手'), findsOneWidget);
    expect(find.text('[圖片]'), findsOneWidget);
    expect(find.text('這張不錯'), findsOneWidget);
    await tester.longPress(find.text('這張不錯'));
    expect(longPressed, 1);
  });

  testWidgets('引用的原訊息不在手機上時顯示提示', (tester) async {
    final reply = ChatMessage(
      id: 'msg_3',
      botId: 'b1',
      userId: 'u1',
      isUser: true,
      messageType: 'text',
      content: {'text': '好', 'quotedMessageId': 'gone'},
      timestamp: DateTime(2026, 1, 1, 9, 1),
    );
    await tester.pumpWidget(_wrap(ChatBubble(message: reply, onAction: (_) {})));
    expect(find.text('原訊息'), findsOneWidget);
    expect(find.text('這則訊息已不在這支手機上'), findsOneWidget);
  });
}
