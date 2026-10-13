import 'package:flutter/material.dart';
import 'screens/chat_screen.dart';
import 'theme/app_theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const LocalBotApp());
}

class LocalBotApp extends StatelessWidget {
  const LocalBotApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'LocalBot',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.system,
      home: const ChatScreen(),
    );
  }
}
