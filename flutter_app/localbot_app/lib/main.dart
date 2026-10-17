import 'dart:async';
import 'package:app_links/app_links.dart';
import 'package:flutter/material.dart';
import 'models/join_link.dart';
import 'screens/bot_list_screen.dart';
import 'screens/join_screen.dart';
import 'services/auth_service.dart';
import 'services/chat_hub.dart';
import 'theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AuthService().init();
  await ChatHub().start();
  runApp(const LocalBotApp());
}

class LocalBotApp extends StatefulWidget {
  const LocalBotApp({super.key});

  @override
  State<LocalBotApp> createState() => _LocalBotAppState();
}

class _LocalBotAppState extends State<LocalBotApp> {
  final GlobalKey<NavigatorState> _navKey = GlobalKey<NavigatorState>();
  final ChatHub _hub = ChatHub();
  StreamSubscription<String>? _linkSub;

  /// 還沒加入任何 Bot 時，連結帶來的邀請會預先填進首頁的加入畫面
  JoinInvite? _invite;
  int _inviteSeq = 0;
  String? _lastLink;
  DateTime _lastLinkAt = DateTime.fromMillisecondsSinceEpoch(0);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _initLinks());
  }

  @override
  void dispose() {
    _linkSub?.cancel();
    super.dispose();
  }

  Future<void> _initLinks() async {
    try {
      final links = AppLinks();
      _linkSub = links.stringLinkStream.listen(_handleLink, onError: (_) {});
      final initial = await links.getInitialLinkString();
      if (initial != null) _handleLink(initial);
    } catch (_) {
      // 不支援連結的平台直接略過
    }
  }

  void _handleLink(String text) {
    final now = DateTime.now();
    // 冷啟動時初始連結可能同時從 getInitialLink 與串流各來一次
    if (text == _lastLink && now.difference(_lastLinkAt) < const Duration(seconds: 3)) return;
    _lastLink = text;
    _lastLinkAt = now;

    final invite = JoinInvite.parse(text);
    if (invite == null || !mounted) return;
    if (_hub.status == HubStatus.ready) {
      _navKey.currentState?.push(
        MaterialPageRoute(builder: (_) => JoinScreen(canCancel: true, initialInvite: invite)),
      );
    } else {
      setState(() {
        _invite = invite;
        _inviteSeq++;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'LocalBot',
      navigatorKey: _navKey,
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.system,
      home: ListenableBuilder(
        listenable: _hub,
        builder: (context, _) {
          switch (_hub.status) {
            case HubStatus.ready:
              return const BotListScreen();
            case HubStatus.revoked:
              return JoinScreen(
                key: ValueKey('revoked-$_inviteSeq'),
                revoked: true,
                initialInvite: _invite,
              );
            case HubStatus.needsJoin:
              return JoinScreen(
                key: ValueKey('join-$_inviteSeq'),
                initialInvite: _invite,
              );
          }
        },
      ),
    );
  }
}
