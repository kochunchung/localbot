import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:file_picker/file_picker.dart';
import 'package:image_picker/image_picker.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:video_player/video_player.dart';

import '../models/bot_info.dart';
import '../models/message.dart';
import '../services/api_service.dart';
import '../services/auth_service.dart';
import '../services/chat_hub.dart';
import '../services/database_service.dart';
import '../services/socket_service.dart';
import '../widgets/chat_bubble.dart';
import '../theme/app_theme.dart';
import '../widgets/bot_avatar.dart';
import '../widgets/sticker_picker.dart';
import '../widgets/rich_menu_panel.dart';
import '../widgets/typing_indicator.dart';
import 'bot_settings_screen.dart';
import 'settings_screen.dart';
import 'location_picker_screen.dart';

class ChatScreen extends StatefulWidget {
  /// 要聊天的 Bot
  final BotInfo bot;

  const ChatScreen({super.key, required this.bot});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final AuthService _auth = AuthService();
  final ApiService _api = ApiService();
  final DatabaseService _db = DatabaseService();
  final ChatHub _hub = ChatHub();
  final ImagePicker _picker = ImagePicker();
  final AudioRecorder _audioRecorder = AudioRecorder();

  final List<ChatMessage> _messages = [];
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  StreamSubscription? _messageSub;
  StreamSubscription? _stateSub;
  StreamSubscription? _loadingSub;
  StreamSubscription? _deliveryFailedSub;

  String get _botId => widget.bot.botId;

  /// 最新的 Bot 資訊（名稱、封鎖狀態會在設定裡改變）
  BotInfo get _bot => _auth.botById(_botId) ?? widget.bot;
  bool get _isBlocked => _bot.blocked;

  /// Bot 呼叫 show_loading_animation 後顯示「輸入中」，收到訊息或逾時即消失
  bool _botTyping = false;
  Timer? _typingTimer;

  /// Rich Menu（null 表示沒有選單）
  Map<String, dynamic>? _richMenu;
  bool _richMenuOpen = false;
  StreamSubscription? _richMenuSub;
  final FocusNode _inputFocus = FocusNode();
  SocketConnectionState _connectionState = SocketConnectionState.disconnected;

  bool _isRecording = false;
  Timer? _recordTimer;
  int _recordSeconds = 0;
  String? _dismissedQuickReplyMsgId;

  /// 長按「回覆」選中的訊息（顯示在輸入列上方）
  ChatMessage? _replyTo;

  /// 打開聊天室時第一則未讀訊息；在它上方顯示「以下為未讀訊息」
  String? _unreadAnchorId;
  final GlobalKey _unreadKey = GlobalKey();

  /// 往上捲動看舊訊息時，右下角顯示「跳到最新」按鈕；期間收到的新訊息數
  bool _showJumpButton = false;
  int _newWhileAway = 0;

  /// QuickReply items are strictly bound to the latest incoming Bot message.
  /// If the latest message is from the user (e.g. user sent text, voice,
  /// image, location, sticker) or does not contain quick reply, it returns null.
  List<dynamic>? get _activeQuickReplyItems {
    if (_messages.isEmpty) return null;
    final lastMsg = _messages.last;
    if (lastMsg.isUser) return null;
    if (lastMsg.id == _dismissedQuickReplyMsgId) return null;
    if (lastMsg.quickReplyItems != null && lastMsg.quickReplyItems!.isNotEmpty) {
      return lastMsg.quickReplyItems;
    }
    return null;
  }

  @override
  void initState() {
    super.initState();
    _initializeApp();
  }

  Future<void> _initializeApp() async {
    _hub.openBotId = _botId;
    _scrollController.addListener(_onScroll);
    final unread = _hub.unreadFor(_botId);
    await _loadLocalMessages();
    if (unread > 0 && unread <= _messages.length && mounted) {
      setState(() => _unreadAnchorId = _messages[_messages.length - unread].id);
      _scrollToUnread();
    }
    await _hub.markRead(_botId);
    _loadRichMenu(initial: true);

    _richMenuSub = _hub.onRichMenuChanged.listen((id) {
      if (id.isEmpty || id == _botId) _loadRichMenu();
    });

    // 開始打字時收起選單（與 LINE 相同，鍵盤與選單二選一）
    _inputFocus.addListener(() {
      if (_inputFocus.hasFocus && _richMenuOpen && mounted) {
        setState(() => _richMenuOpen = false);
      }
    });

    // Setup Socket.IO listeners
    _connectionState = _hub.connectionState;
    _stateSub = _hub.onConnectionState.listen((state) {
      if (mounted) {
        setState(() => _connectionState = state);
      }
    });

    _messageSub = _hub.onMessage.listen((message) {
      if (message.botId == _botId) _addIncomingMessage(message);
    });

    _loadingSub = _hub.onTyping.listen((event) {
      if (event.$1 == _botId && mounted) _showTyping(event.$2);
    });

    // 快速送出後，伺服器在背景轉給 Bot 失敗時通知：把那幾則標成「無法傳送」
    _deliveryFailedSub = _hub.onDeliveryFailed.listen((event) {
      final (botId, ids) = event;
      if (botId != _botId || !mounted) return;
      var changed = false;
      for (final m in _messages) {
        if (m.isUser && ids.contains(m.id) && m.status != 'failed') {
          m.status = 'failed';
          _hub.takeFailed(m.id);
          changed = true;
        }
      }
      if (changed) {
        setState(() {});
        _showSnack('Bot 沒有收到訊息，請稍後再試');
      }
    });
  }

  @override
  void dispose() {
    if (_hub.openBotId == _botId) _hub.openBotId = null;
    _messageSub?.cancel();
    _stateSub?.cancel();
    _loadingSub?.cancel();
    _deliveryFailedSub?.cancel();
    _typingTimer?.cancel();
    _richMenuSub?.cancel();
    _scrollController.removeListener(_onScroll);
    _inputFocus.dispose();
    _recordTimer?.cancel();
    _audioRecorder.dispose();
    _textController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadLocalMessages() async {
    final localMsgs = await _db.getMessages(_botId, limit: 100);
    if (mounted) {
      setState(() {
        _messages.clear();
        _messages.addAll(localMsgs);
        _dismissedQuickReplyMsgId = null;
      });
      _scrollToBottom();
    }
  }

  /// 自己送出的訊息：存進本機資料庫並更新 Bot 清單上的預覽
  Future<void> _saveLocal(ChatMessage message) async {
    // 伺服器的「送不到」通知可能比 HTTP 回應更早到
    if (message.isUser && _hub.takeFailed(message.id)) message.status = 'failed';
    await _db.saveMessage(message);
    _hub.noteLocalMessage(message);
  }

  /// 離最底部夠近（使用者正在看最新訊息）
  bool get _nearBottom {
    if (!_scrollController.hasClients) return true;
    final pos = _scrollController.position;
    return pos.maxScrollExtent - pos.pixels < 200;
  }

  void _onScroll() {
    if (!_scrollController.hasClients) return;
    final pos = _scrollController.position;
    final away = pos.maxScrollExtent - pos.pixels > 400;
    if (away != _showJumpButton || (!away && _newWhileAway > 0)) {
      setState(() {
        _showJumpButton = away;
        if (!away) _newWhileAway = 0;
      });
    }
  }

  /// 打開聊天室時有未讀：先到底部，再把「以下為未讀訊息」捲到畫面上方
  void _scrollToUnread() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scrollController.hasClients) return;
      _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final ctx = _unreadKey.currentContext;
        if (ctx == null || !mounted) return;
        Scrollable.ensureVisible(ctx, alignment: 0.05, duration: const Duration(milliseconds: 200));
      });
    });
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  /// 訊息已由 ChatHub 存進本機資料庫，這裡只負責顯示並標為已讀
  Future<void> _addIncomingMessage(ChatMessage message) async {
    await _hub.markRead(_botId);
    if (mounted) {
      _typingTimer?.cancel();
      // 正在往上看舊訊息時不要硬拉到底部，改在「跳到最新」按鈕上顯示新訊息數
      final follow = _nearBottom;
      setState(() {
        _messages.add(message);
        _dismissedQuickReplyMsgId = null;
        _botTyping = false;
        if (!follow) _newWhileAway++;
      });
      if (follow) _scrollToBottom();
    }
  }

  /// 載入 Rich Menu；第一次載入時依 selected 決定是否預設展開
  Future<void> _loadRichMenu({bool initial = false}) async {
    final menu = _isBlocked ? null : await _api.fetchRichMenu(_botId);
    if (!mounted) return;
    final changed = menu?['richMenuId'] != _richMenu?['richMenuId'];
    setState(() {
      _richMenu = menu;
      if (menu == null) {
        _richMenuOpen = false;
      } else if (initial || changed) {
        _richMenuOpen = menu['selected'] == true;
      }
    });
  }

  void _toggleRichMenu() {
    final open = !_richMenuOpen;
    if (open) _inputFocus.unfocus();
    setState(() => _richMenuOpen = open);
  }

  /// richmenuswitch：切換選單後送 postback（params 內含 newRichMenuAliasId 與 status）
  Future<void> _switchRichMenu(Map<String, dynamic> action) async {
    final aliasId = (action['richMenuAliasId'] ?? '').toString();
    final (status, menu) = await _api.switchRichMenu(_botId, aliasId);
    if (!mounted) return;
    if (menu != null) {
      setState(() {
        _richMenu = menu;
        _richMenuOpen = true;
      });
    }
    await _api.sendPostback(
      _botId,
      (action['data'] ?? '').toString(),
      params: {'newRichMenuAliasId': aliasId, 'status': status},
    );
    if (status != 'SUCCESS') _showSnack('無法切換選單（$status）');
  }

  void _showTyping(int seconds) {
    _typingTimer?.cancel();
    final follow = _nearBottom;
    setState(() => _botTyping = true);
    if (follow) _scrollToBottom();
    _typingTimer = Timer(Duration(seconds: seconds), () {
      if (mounted) setState(() => _botTyping = false);
    });
  }

  // ==========================================================================
  // Sending Actions
  // ==========================================================================

  /// 傳送輸入框中的文字
  Future<void> _sendText() async {
    final text = _textController.text.trim();
    if (text.isEmpty) return;

    _textController.clear();
    final quoted = _replyTo?.id;
    if (quoted != null) setState(() => _replyTo = null);
    await _sendTextValue(text, quotedMessageId: quoted);
  }

  /// 傳送指定文字（Quick Reply、範本按鈕、重送等），不會動到輸入框
  Future<void> _sendTextValue(String text, {String? quotedMessageId}) async {
    final optimisticMsg = ChatMessage(
      id: 'local_${DateTime.now().millisecondsSinceEpoch}',
      botId: _botId,
      userId: _auth.userId,
      isUser: true,
      messageType: 'text',
      content: {
        'text': text,
        if (quotedMessageId != null) 'quotedMessageId': quotedMessageId,
      },
      timestamp: DateTime.now(),
      status: 'sending',
    );

    setState(() {
      _messages.add(optimisticMsg);
    });
    _scrollToBottom();

    final resultMsg = await _api.sendTextMessage(_botId, text, quotedMessageId: quotedMessageId);

    if (resultMsg != null) {
      await _saveLocal(resultMsg);
      if (!mounted) return;
      setState(() {
        final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
        if (idx != -1) {
          _messages[idx] = resultMsg;
        }
      });
    } else {
      if (!mounted) return;
      setState(() {
        optimisticMsg.status = 'failed';
      });
    }
  }

  Future<void> _pickAndSendImage(ImageSource source) async {
    try {
      final XFile? file = await _picker.pickImage(source: source, imageQuality: 85);
      if (file == null) return;

      final imageFile = File(file.path);

      final optimisticMsg = ChatMessage(
        id: 'local_img_${DateTime.now().millisecondsSinceEpoch}',
        botId: _botId,
        userId: _auth.userId,
        isUser: true,
        messageType: 'image',
        content: {'originalContentUrl': 'file://${file.path}'},
        timestamp: DateTime.now(),
        status: 'sending',
      );

      setState(() {
        _messages.add(optimisticMsg);
      });
      _scrollToBottom();

      final sentMsg = await _api.uploadAndSendMedia(_botId, imageFile, 'image');
      if (sentMsg != null) {
        await _saveLocal(sentMsg);
        if (!mounted) return;
        setState(() {
          final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
          if (idx != -1) {
            _messages[idx] = sentMsg;
          }
        });
      } else {
        if (!mounted) return;
        setState(() {
          optimisticMsg.status = 'failed';
        });
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('選取圖片失敗: $e')),
      );
    }
  }

  /// 允許傳送的檔案類型（需與伺服器 ALLOWED_UPLOAD_EXTENSIONS 一致）
  static const Set<String> _allowedFileExtensions = {
    'pdf', 'txt', 'csv', 'json', 'zip',
    'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp',
    'jpg', 'jpeg', 'png', 'gif', 'webp', 'heic',
    'mp3', 'm4a', 'aac', 'wav', 'ogg', 'opus',
    'mp4', 'mov', '3gp', 'webm',
  };

  /// 上傳影片 / 檔案：先顯示「傳送中」，完成後換成正式訊息
  Future<void> _sendMediaFile(
    File file,
    String mediaType, {
    int duration = 0,
    String? fileName,
    int? fileSize,
  }) async {
    final optimisticMsg = ChatMessage(
      id: 'local_${mediaType}_${DateTime.now().millisecondsSinceEpoch}',
      botId: _botId,
      userId: _auth.userId,
      isUser: true,
      messageType: mediaType,
      content: {
        'originalContentUrl': 'file://${file.path}',
        if (mediaType == 'video') 'duration': duration,
        if (fileName != null) 'fileName': fileName,
        if (fileSize != null) 'fileSize': fileSize,
      },
      timestamp: DateTime.now(),
      status: 'sending',
    );

    setState(() => _messages.add(optimisticMsg));
    _scrollToBottom();

    final sentMsg = await _api.uploadAndSendMedia(
      _botId,
      file,
      mediaType,
      duration: duration,
      fileName: fileName,
      fileSize: fileSize,
    );
    if (sentMsg != null) {
      await _saveLocal(sentMsg);
    }
    if (!mounted) return;
    setState(() {
      if (sentMsg != null) {
        final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
        if (idx != -1) _messages[idx] = sentMsg;
      } else {
        optimisticMsg.status = 'failed';
      }
    });
  }

  /// 讀取影片長度（毫秒），失敗時回傳 0
  Future<int> _probeVideoDuration(File file) async {
    final controller = VideoPlayerController.file(file);
    try {
      await controller.initialize();
      return controller.value.duration.inMilliseconds;
    } catch (_) {
      return 0;
    } finally {
      await controller.dispose();
    }
  }

  Future<void> _pickAndSendVideo() async {
    try {
      final XFile? picked = await _picker.pickVideo(
        source: ImageSource.gallery,
        maxDuration: const Duration(minutes: 5),
      );
      if (picked == null) return;
      final file = File(picked.path);
      final durationMs = await _probeVideoDuration(file);
      if (!mounted) return;
      await _sendMediaFile(file, 'video', duration: durationMs);
    } catch (e) {
      _showSnack('選取影片失敗: $e');
    }
  }

  Future<void> _pickAndSendFile() async {
    try {
      final result = await FilePicker.platform.pickFiles();
      if (result == null || result.files.isEmpty) return;
      final picked = result.files.first;
      final path = picked.path;
      if (path == null) return;
      final ext = (picked.extension ?? '').toLowerCase();
      if (!_allowedFileExtensions.contains(ext)) {
        _showSnack('不支援的檔案類型：.$ext');
        return;
      }
      if (!mounted) return;
      await _sendMediaFile(
        File(path),
        'file',
        fileName: picked.name,
        fileSize: picked.size,
      );
    } catch (e) {
      _showSnack('選取檔案失敗: $e');
    }
  }

  Future<void> _startRecording() async {
    try {
      if (await _audioRecorder.hasPermission()) {
        final tempDir = await getTemporaryDirectory();
        final path = '${tempDir.path}/audio_${DateTime.now().millisecondsSinceEpoch}.m4a';

        const config = RecordConfig(encoder: AudioEncoder.aacLc, bitRate: 64000);
        await _audioRecorder.start(config, path: path);

        setState(() {
          _isRecording = true;
          _recordSeconds = 0;
        });

        _recordTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
          if (mounted) {
            setState(() {
              _recordSeconds++;
            });
          }
        });
      } else {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('請授予麥克風權限以進行錄音')),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('啟動錄音失敗: $e')),
      );
    }
  }

  Future<void> _stopAndSendRecording({bool cancel = false}) async {
    _recordTimer?.cancel();
    final path = await _audioRecorder.stop();
    if (!mounted) return;

    setState(() {
      _isRecording = false;
    });

    if (cancel || path == null) return;

    final durationMs = _recordSeconds * 1000;
    final audioFile = File(path);

    final optimisticMsg = ChatMessage(
      id: 'local_audio_${DateTime.now().millisecondsSinceEpoch}',
      botId: _botId,
      userId: _auth.userId,
      isUser: true,
      messageType: 'audio',
      content: {'originalContentUrl': 'file://$path', 'duration': durationMs},
      timestamp: DateTime.now(),
      status: 'sending',
    );

    setState(() {
      _messages.add(optimisticMsg);
    });
    _scrollToBottom();

    final sentMsg = await _api.uploadAndSendMedia(_botId, audioFile, 'audio', duration: durationMs);
    if (sentMsg != null) {
      await _saveLocal(sentMsg);
      if (!mounted) return;
      setState(() {
        final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
        if (idx != -1) {
          _messages[idx] = sentMsg;
        }
      });
    } else {
      if (!mounted) return;
      setState(() {
        optimisticMsg.status = 'failed';
      });
    }
  }

  Future<void> _sendLocation({
    required String title,
    required String address,
    required double latitude,
    required double longitude,
  }) async {
    final optimisticMsg = ChatMessage(
      id: 'local_loc_${DateTime.now().millisecondsSinceEpoch}',
      botId: _botId,
      userId: _auth.userId,
      isUser: true,
      messageType: 'location',
      content: {
        'title': title,
        'address': address,
        'latitude': latitude,
        'longitude': longitude,
      },
      timestamp: DateTime.now(),
      status: 'sending',
    );

    setState(() {
      _messages.add(optimisticMsg);
    });
    _scrollToBottom();

    final sentMsg = await _api.sendLocationMessage(
      _botId,
      title: title,
      address: address,
      latitude: latitude,
      longitude: longitude,
    );

    if (sentMsg != null) {
      await _saveLocal(sentMsg);
      if (!mounted) return;
      setState(() {
        final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
        if (idx != -1) {
          _messages[idx] = sentMsg;
        }
      });
    } else {
      if (!mounted) return;
      setState(() {
        optimisticMsg.status = 'failed';
      });
    }
  }

  Future<void> _openLocationPicker() async {
    final result = await Navigator.push<Map<String, dynamic>>(
      context,
      MaterialPageRoute(
        builder: (_) => const LocationPickerScreen(),
      ),
    );

    if (result != null) {
      final title = result['title'] as String? ?? '選取位置';
      final address = result['address'] as String? ?? '';
      final lat = (result['latitude'] as num?)?.toDouble() ?? 25.0339;
      final lng = (result['longitude'] as num?)?.toDouble() ?? 121.5644;

      _sendLocation(
        title: title,
        address: address,
        latitude: lat,
        longitude: lng,
      );
    }
  }

  void _openStickerPicker() {
    showModalBottomSheet(
      context: context,
      builder: (_) => StickerPickerWidget(
        onStickerSelected: (packageId, stickerId) async {
          final optimisticMsg = ChatMessage(
            id: 'local_stk_${DateTime.now().millisecondsSinceEpoch}',
            botId: _botId,
            userId: _auth.userId,
            isUser: true,
            messageType: 'sticker',
            content: {'packageId': packageId, 'stickerId': stickerId},
            timestamp: DateTime.now(),
            status: 'sending',
          );

          setState(() {
            _messages.add(optimisticMsg);
          });
          _scrollToBottom();

          final sentMsg = await _api.sendSticker(_botId, packageId, stickerId);
          if (sentMsg != null) {
            await _saveLocal(sentMsg);
            if (!mounted) return;
            setState(() {
              final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
              if (idx != -1) {
                _messages[idx] = sentMsg;
              }
            });
          } else {
            if (!mounted) return;
            setState(() {
              optimisticMsg.status = 'failed';
            });
          }
        },
      ),
    );
  }

  /// 收合目前的 Quick Reply（與 LINE 相同：點選按鈕後即消失）
  void _dismissQuickReply() {
    if (_messages.isEmpty) return;
    setState(() => _dismissedQuickReplyMsgId = _messages.last.id);
  }

  void _showSnack(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  /// 處理 Quick Reply、範本與 Flex 按鈕的動作
  Future<void> _handleAction(Map<String, dynamic> action) async {
    final type = action['type']?.toString();
    switch (type) {
      case 'postback':
        _dismissQuickReply();
        await _sendPostbackAction(action);
      case 'message':
        final text = (action['text'] ?? action['label'] ?? '').toString();
        if (text.isEmpty) return;
        _dismissQuickReply();
        await _sendTextValue(text);
      case 'uri':
        _dismissQuickReply();
        await _openUri((action['uri'] ?? '').toString());
      case 'datetimepicker':
        final value = await _pickDatetime(action);
        if (value == null || !mounted) return;
        _dismissQuickReply();
        final mode = (action['mode'] ?? 'datetime').toString();
        await _sendPostbackAction(action, params: {mode: value});
      case 'clipboard':
        final text = (action['clipboardText'] ?? '').toString();
        await Clipboard.setData(ClipboardData(text: text));
        _showSnack('已複製到剪貼簿');
      case 'camera':
        _dismissQuickReply();
        await _pickAndSendImage(ImageSource.camera);
      case 'cameraRoll':
        _dismissQuickReply();
        await _pickAndSendImage(ImageSource.gallery);
      case 'location':
        _dismissQuickReply();
        await _openLocationPicker();
      case 'richmenuswitch':
        await _switchRichMenu(action);
      default:
        _showSnack('尚未支援的動作：${type ?? '未知'}');
    }
  }

  /// 送出 postback 事件；有 displayText（舊版為 text）時才在聊天室顯示使用者的選擇
  Future<void> _sendPostbackAction(
    Map<String, dynamic> action, {
    Map<String, String>? params,
  }) async {
    final data = (action['data'] ?? '').toString();
    final display = (action['displayText'] ?? action['text'])?.toString();

    if (display != null && display.isNotEmpty) {
      final echoMsg = ChatMessage(
        id: 'pb_echo_${DateTime.now().millisecondsSinceEpoch}',
        botId: _botId,
        userId: _auth.userId,
        isUser: true,
        messageType: 'text',
        content: {'text': display},
        timestamp: DateTime.now(),
        status: 'sending',
      );
      setState(() => _messages.add(echoMsg));
      _scrollToBottom();

      final ok = await _api.sendPostback(_botId, data, displayText: display, params: params);
      echoMsg.status = ok ? 'sent' : 'failed';
      await _saveLocal(echoMsg);
      if (mounted) setState(() {});
    } else {
      final ok = await _api.sendPostback(_botId, data, params: params);
      if (!ok) _showSnack('傳送失敗，請檢查連線');
    }

    // inputOption：openKeyboard 時打開鍵盤並帶入預設文字
    if (!mounted) return;
    if (action['inputOption'] == 'openKeyboard') {
      final fill = action['fillInText']?.toString();
      if (fill != null && fill.isNotEmpty) {
        _textController.text = fill;
      }
    }
  }

  /// 以外部瀏覽器 / App 開啟連結（只允許 http、https、tel、mailto）
  Future<void> _openUri(String raw) async {
    const allowedSchemes = {'http', 'https', 'tel', 'mailto'};
    final uri = Uri.tryParse(raw.trim());
    if (uri == null || !allowedSchemes.contains(uri.scheme.toLowerCase())) {
      _showSnack('無法開啟這個連結');
      return;
    }
    var ok = false;
    try {
      ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {
      ok = false;
    }
    if (!ok) _showSnack('無法開啟連結：$raw');
  }

  /// 日期時間選擇器，回傳 LINE 格式：date `2026-10-13`、time `09:30`、datetime `2026-10-13T09:30`
  Future<String?> _pickDatetime(Map<String, dynamic> action) async {
    final mode = (action['mode'] ?? 'datetime').toString();
    final now = DateTime.now();

    DateTime? parse(dynamic value) {
      if (value == null) return null;
      final text = value.toString();
      if (mode == 'time') {
        final parts = text.split(':');
        if (parts.length < 2) return null;
        final h = int.tryParse(parts[0]);
        final m = int.tryParse(parts[1]);
        if (h == null || m == null) return null;
        return DateTime(now.year, now.month, now.day, h, m);
      }
      return DateTime.tryParse(text);
    }

    String two(int n) => n.toString().padLeft(2, '0');
    String fmtDate(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${two(d.month)}-${two(d.day)}';
    String fmtTime(TimeOfDay t) => '${two(t.hour)}:${two(t.minute)}';

    final initial = parse(action['initial']) ?? now;

    if (mode == 'time') {
      final time = await showTimePicker(
        context: context,
        initialTime: TimeOfDay.fromDateTime(initial),
      );
      return time == null ? null : fmtTime(time);
    }

    final first = parse(action['min']) ?? DateTime(1900);
    final last = parse(action['max']) ?? DateTime(2100, 12, 31);
    var initDate = initial;
    if (initDate.isBefore(first)) initDate = first;
    if (initDate.isAfter(last)) initDate = last;

    final date = await showDatePicker(
      context: context,
      initialDate: initDate,
      firstDate: first,
      lastDate: last,
    );
    if (date == null) return null;
    if (mode == 'date') return fmtDate(date);

    if (!mounted) return null;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(initDate),
    );
    if (time == null) return null;
    return '${fmtDate(date)}T${fmtTime(time)}';
  }

  // ==========================================================================
  // UI Builder
  // ==========================================================================

  static bool _sameDay(DateTime a, DateTime b) =>
      a.year == b.year && a.month == b.month && a.day == b.day;

  String _dateLabel(DateTime d) {
    final now = DateTime.now();
    if (_sameDay(d, now)) return '今天';
    if (_sameDay(d, now.subtract(const Duration(days: 1)))) return '昨天';
    const weekdays = ['一', '二', '三', '四', '五', '六', '日'];
    final w = '週${weekdays[d.weekday - 1]}';
    if (d.year == now.year) return '${d.month}月${d.day}日 $w';
    return '${d.year}年${d.month}月${d.day}日 $w';
  }

  /// 是否為同一串（同一發送者、同一天、間隔 3 分鐘內）
  bool _isSameGroup(ChatMessage a, ChatMessage b) {
    return a.isUser == b.isUser &&
        _sameDay(a.timestamp, b.timestamp) &&
        b.timestamp.difference(a.timestamp).inMinutes.abs() < 3;
  }

  void _retryMessage(ChatMessage msg) {
    if (msg.messageType != 'text') return;
    setState(() => _messages.removeWhere((m) => m.id == msg.id));
    unawaited(_db.deleteMessage(_botId, msg.id));
    _sendTextValue(msg.text, quotedMessageId: msg.quotedMessageId);
  }

  // ==========================================================================
  // 長按選單：回覆 / 複製 / 重新傳送 / 刪除
  // ==========================================================================

  String _senderName(ChatMessage m) => m.isUser ? '你' : _bot.name;

  void _showMessageMenu(ChatMessage msg) {
    final canReply = !_isBlocked && !msg.id.startsWith('local_') && msg.status != 'sending';
    final canCopy = msg.text.trim().isNotEmpty;
    final canResend = msg.isUser && msg.status == 'failed' && msg.messageType == 'text';
    HapticFeedback.selectionClick();
    _inputFocus.unfocus();
    showModalBottomSheet(
      context: context,
      showDragHandle: true,
      builder: (ctx) {
        final scheme = Theme.of(ctx).colorScheme;
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
                child: Text(
                  msg.summary,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: scheme.onSurfaceVariant),
                ),
              ),
              if (canReply)
                ListTile(
                  leading: const Icon(Icons.reply_rounded),
                  title: const Text('回覆'),
                  onTap: () {
                    Navigator.pop(ctx);
                    _startReply(msg);
                  },
                ),
              if (canCopy)
                ListTile(
                  leading: const Icon(Icons.copy_rounded),
                  title: const Text('複製'),
                  onTap: () {
                    Navigator.pop(ctx);
                    Clipboard.setData(ClipboardData(text: msg.text));
                    _showSnack('已複製');
                  },
                ),
              if (canResend)
                ListTile(
                  leading: const Icon(Icons.refresh_rounded),
                  title: const Text('重新傳送'),
                  onTap: () {
                    Navigator.pop(ctx);
                    _retryMessage(msg);
                  },
                ),
              ListTile(
                leading: Icon(Icons.delete_outline_rounded, color: scheme.error),
                title: Text('刪除', style: TextStyle(color: scheme.error)),
                subtitle: const Text('只刪除這支手機上的紀錄，Bot 那邊不受影響'),
                onTap: () {
                  Navigator.pop(ctx);
                  _deleteLocal(msg);
                },
              ),
              const SizedBox(height: 8),
            ],
          ),
        );
      },
    );
  }

  void _startReply(ChatMessage msg) {
    setState(() {
      _replyTo = msg;
      _richMenuOpen = false;
    });
    _inputFocus.requestFocus();
  }

  Future<void> _deleteLocal(ChatMessage msg) async {
    setState(() {
      _messages.removeWhere((m) => m.id == msg.id);
      if (_replyTo?.id == msg.id) _replyTo = null;
    });
    await _db.deleteMessage(_botId, msg.id);
    await _hub.reload();
  }

  ChatMessage? _findMessage(String id) {
    for (final m in _messages) {
      if (m.id == id) return m;
    }
    return null;
  }

  /// 輸入列上方的「回覆 ○○」
  Widget _buildReplyBar() {
    final r = _replyTo;
    if (r == null || _isBlocked || _isRecording) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 6, 4, 0),
      child: Row(
        children: [
          Icon(Icons.reply_rounded, size: 18, color: scheme.primary),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  '回覆 ${_senderName(r)}',
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: scheme.primary),
                ),
                Text(
                  r.summary,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 13, color: scheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.close_rounded, size: 18),
            tooltip: '取消回覆',
            onPressed: () => setState(() => _replyTo = null),
          ),
        ],
      ),
    );
  }

  /// 往上捲動時出現的「跳到最新」按鈕（有新訊息時顯示數量）
  Widget _buildJumpButton() {
    final scheme = Theme.of(context).colorScheme;
    return Positioned(
      right: 12,
      bottom: 12,
      child: IgnorePointer(
        ignoring: !_showJumpButton,
        child: AnimatedScale(
        scale: _showJumpButton ? 1 : 0,
        duration: const Duration(milliseconds: 150),
        child: Material(
          color: scheme.surface,
          elevation: 3,
          shape: const StadiumBorder(),
          child: InkWell(
            customBorder: const StadiumBorder(),
            onTap: () {
              setState(() => _newWhileAway = 0);
              _scrollToBottom();
            },
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (_newWhileAway > 0) ...[
                    Text(
                      '$_newWhileAway 則新訊息',
                      style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: scheme.primary),
                    ),
                    const SizedBox(width: 4),
                  ],
                  Icon(Icons.keyboard_double_arrow_down_rounded, size: 20, color: scheme.primary),
                ],
              ),
            ),
          ),
        ),
      ),
      ),
    );
  }

  Widget _buildMessageItem(int index) {
    final msg = _messages[index];
    final prev = index > 0 ? _messages[index - 1] : null;
    final next = index < _messages.length - 1 ? _messages[index + 1] : null;

    final showDate = prev == null || !_sameDay(prev.timestamp, msg.timestamp);
    final startsGroup = prev == null || showDate || !_isSameGroup(prev, msg);
    final endsGroup = next == null || !_isSameGroup(msg, next);

    final quotedId = msg.quotedMessageId;
    final quoted = quotedId == null ? null : _findMessage(quotedId);

    final bubble = ChatBubble(
      message: msg,
      onAction: _handleAction,
      showAvatar: startsGroup,
      showMeta: endsGroup,
      onRetry: msg.isUser && msg.messageType == 'text' && !msg.id.startsWith('pb_echo_')
          ? () => _retryMessage(msg)
          : null,
      onLongPress: () => _showMessageMenu(msg),
      quoted: quoted,
      quotedSender: quoted == null ? null : _senderName(quoted),
      botAvatarUrl: _bot.avatarUrl,
    );

    final isUnreadAnchor = msg.id == _unreadAnchorId;
    if (!showDate && !isUnreadAnchor) return bubble;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (showDate) _DateDivider(label: _dateLabel(msg.timestamp)),
        if (isUnreadAnchor) _UnreadDivider(key: _unreadKey),
        bubble,
      ],
    );
  }

  Widget _buildQuickReplyChip(dynamic item, ColorScheme scheme) {
    final action = item is Map ? (item['action'] ?? item) : {};
    final label = action['label'] ?? action['text'] ?? action['type'] ?? '選項';
    final imageUrl = item is Map ? item['imageUrl'] : null;

    Widget? avatar;
    if (imageUrl != null && imageUrl.toString().isNotEmpty) {
      avatar = Image.network(
        imageUrl.toString(),
        width: 18,
        height: 18,
        errorBuilder: (_, __, ___) => const Icon(Icons.touch_app, size: 16),
      );
    } else if (action['type'] == 'camera') {
      avatar = const Icon(Icons.photo_camera_outlined, size: 16);
    } else if (action['type'] == 'cameraRoll') {
      avatar = const Icon(Icons.photo_library_outlined, size: 16);
    } else if (action['type'] == 'location') {
      avatar = const Icon(Icons.place_outlined, size: 16);
    }

    return ActionChip(
      avatar: avatar,
      label: Text(label.toString()),
      labelStyle: TextStyle(
        fontSize: 13,
        fontWeight: FontWeight.w600,
        color: scheme.primary,
      ),
      side: BorderSide(color: scheme.primary.withValues(alpha: 0.5)),
      backgroundColor: scheme.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      onPressed: () {
        if (action is Map<String, dynamic>) {
          _handleAction(action);
        } else if (action is Map) {
          _handleAction(Map<String, dynamic>.from(action));
        }
      },
    );
  }

  Widget _buildQuickReplyBar() {
    final items = _activeQuickReplyItems;
    if (items == null || items.isEmpty || _isBlocked) {
      return const SizedBox.shrink();
    }
    final scheme = Theme.of(context).colorScheme;

    return SizedBox(
      height: 48,
      child: Row(
        children: [
          Expanded(
            // 選項放得下時置中（例如只有一個），放不下時從左邊開始、可以左右滑動
            child: LayoutBuilder(
              builder: (context, constraints) => SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                child: ConstrainedBox(
                  constraints: BoxConstraints(minWidth: (constraints.maxWidth - 24).clamp(0.0, double.infinity)),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      for (var index = 0; index < items.length; index++) ...[
                        if (index > 0) const SizedBox(width: 8),
                        _buildQuickReplyChip(items[index], scheme),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
          IconButton(
            icon: Icon(Icons.close_rounded, size: 18, color: scheme.onSurfaceVariant),
            tooltip: '收合快速回覆',
            onPressed: () {
              setState(() {
                if (_messages.isNotEmpty) {
                  _dismissedQuickReplyMsgId = _messages.last.id;
                }
              });
            },
          ),
        ],
      ),
    );
  }

  ({Color color, String text}) get _connectionInfo => switch (_connectionState) {
        SocketConnectionState.connected => (color: AppTheme.statusOnline, text: '線上'),
        SocketConnectionState.connecting => (color: AppTheme.statusConnecting, text: '連線中…'),
        SocketConnectionState.disconnected => (color: AppTheme.statusOffline, text: '離線'),
      };

  PreferredSizeWidget _buildAppBar() {
    final scheme = Theme.of(context).colorScheme;
    final info = _connectionInfo;

    return AppBar(
      backgroundColor: scheme.surface,
      surfaceTintColor: Colors.transparent,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleSpacing: 12,
      title: Row(
        children: [
          Stack(
            clipBehavior: Clip.none,
            children: [
              BotAvatar(size: 38, url: _bot.avatarUrl),
              Positioned(
                right: -2,
                bottom: -2,
                child: Container(
                  width: 12,
                  height: 12,
                  decoration: BoxDecoration(
                    color: info.color,
                    shape: BoxShape.circle,
                    border: Border.all(color: scheme.surface, width: 2),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _bot.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
                Text(
                  info.text,
                  style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
        ],
      ),
      actions: [
        IconButton(
          icon: const Icon(Icons.sync_rounded),
          tooltip: '從伺服器同步紀錄',
          onPressed: _syncHistory,
        ),
        IconButton(
          icon: const Icon(Icons.tune_rounded),
          tooltip: '設定',
          onPressed: _openSettings,
        ),
        const SizedBox(width: 4),
      ],
      bottom: PreferredSize(
        preferredSize: const Size.fromHeight(1),
        child: Divider(height: 1, color: scheme.outlineVariant.withValues(alpha: 0.5)),
      ),
    );
  }

  Future<void> _syncHistory() async {
    final history = await _api.fetchHistory(_botId);
    if (!mounted) return;
    if (history.isNotEmpty) {
      for (final h in history) {
        await _saveLocal(h);
      }
      await _loadLocalMessages();
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(history.isEmpty ? '沒有可同步的紀錄' : '已同步 ${history.length} 則訊息')),
    );
  }

  /// 這個 Bot 的設定（封鎖、刪除好友、清除本機紀錄）
  Future<void> _openSettings() async {
    final result = await Navigator.push<BotSettingsResult>(
      context,
      MaterialPageRoute(builder: (_) => BotSettingsScreen(bot: _bot)),
    );
    if (!mounted) return;
    if (result == BotSettingsResult.left) {
      Navigator.pop(context); // 已刪除好友：回到 Bot 清單
      return;
    }
    if (result == BotSettingsResult.clearedHistory) {
      await _loadLocalMessages();
      await _hub.reload();
    }
    // 封鎖狀態可能已改變，重新繪製並重新載入選單
    if (!mounted) return;
    setState(() {});
    _loadRichMenu();
  }

  /// 連線問題時打開全域設定（伺服器網址、顯示名稱）
  Future<void> _openGlobalSettings() async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const SettingsScreen()),
    );
    if (!mounted) return;
    setState(() {});
  }

  Future<void> _unblock() async {
    final ok = await _auth.setBlocked(_botId, false);
    if (!mounted) return;
    setState(() {});
    if (ok) {
      await _hub.reload();
      _loadRichMenu(initial: true);
    }
    _showSnack(ok ? '已解除封鎖' : '無法連線到伺服器，請稍後再試');
  }

  /// 封鎖 Bot 後取代輸入列
  Widget _buildBlockedBar() {
    final scheme = Theme.of(context).colorScheme;
    return Row(
      children: [
        Icon(Icons.block_rounded, color: scheme.onSurfaceVariant),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            '你已封鎖這個 Bot，不會收到它的訊息',
            style: TextStyle(color: scheme.onSurfaceVariant),
          ),
        ),
        TextButton(
          onPressed: _unblock,
          child: const Text('解除封鎖'),
        ),
      ],
    );
  }

  Widget _buildOfflineBanner() {
    if (_connectionState != SocketConnectionState.disconnected) {
      return const SizedBox.shrink();
    }
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: scheme.errorContainer,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 6, 8, 6),
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
            TextButton(
              onPressed: _openGlobalSettings,
              child: const Text('檢查設定'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    final scheme = Theme.of(context).colorScheme;
    const suggestions = ['你好', '你可以做什麼？'];

    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            BotAvatar(size: 72, url: _bot.avatarUrl),
            const SizedBox(height: 16),
            Text(
              _bot.name,
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 6),
            Text(
              '訊息只會傳到你自己架設的伺服器。\n傳一句話開始對話吧。',
              textAlign: TextAlign.center,
              style: TextStyle(color: scheme.onSurfaceVariant, height: 1.5),
            ),
            const SizedBox(height: 20),
            Wrap(
              alignment: WrapAlignment.center,
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final s in suggestions)
                  ActionChip(
                    label: Text(s),
                    onPressed: () => _sendTextValue(s),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  void _openAttachmentSheet() {
    showModalBottomSheet(
      context: context,
      showDragHandle: true,
      builder: (ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
            child: Wrap(
              alignment: WrapAlignment.spaceAround,
              spacing: 8,
              runSpacing: 8,
              children: [
                _AttachmentTile(
                  icon: Icons.photo_library_rounded,
                  label: '相簿',
                  color: const Color(0xFF7C3AED),
                  onTap: () {
                    Navigator.pop(ctx);
                    _pickAndSendImage(ImageSource.gallery);
                  },
                ),
                _AttachmentTile(
                  icon: Icons.photo_camera_rounded,
                  label: '相機',
                  color: const Color(0xFF2563EB),
                  onTap: () {
                    Navigator.pop(ctx);
                    _pickAndSendImage(ImageSource.camera);
                  },
                ),
                _AttachmentTile(
                  icon: Icons.videocam_rounded,
                  label: '影片',
                  color: const Color(0xFFDB2777),
                  onTap: () {
                    Navigator.pop(ctx);
                    _pickAndSendVideo();
                  },
                ),
                _AttachmentTile(
                  icon: Icons.attach_file_rounded,
                  label: '檔案',
                  color: const Color(0xFF475569),
                  onTap: () {
                    Navigator.pop(ctx);
                    _pickAndSendFile();
                  },
                ),
                _AttachmentTile(
                  icon: Icons.place_rounded,
                  label: '位置',
                  color: const Color(0xFF059669),
                  onTap: () {
                    Navigator.pop(ctx);
                    _openLocationPicker();
                  },
                ),
                _AttachmentTile(
                  icon: Icons.emoji_emotions_rounded,
                  label: '貼圖',
                  color: const Color(0xFFD97706),
                  onTap: () {
                    Navigator.pop(ctx);
                    _openStickerPicker();
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  String _formatRecordTime(int seconds) {
    final m = (seconds ~/ 60).toString().padLeft(2, '0');
    final s = (seconds % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  Widget _buildRecordingBar() {
    final scheme = Theme.of(context).colorScheme;
    return Row(
      children: [
        IconButton(
          icon: Icon(Icons.delete_outline_rounded, color: scheme.error),
          tooltip: '取消錄音',
          onPressed: () => _stopAndSendRecording(cancel: true),
        ),
        Expanded(
          child: Container(
            height: 44,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            decoration: BoxDecoration(
              color: scheme.errorContainer.withValues(alpha: 0.6),
              borderRadius: BorderRadius.circular(22),
            ),
            child: Row(
              children: [
                Icon(Icons.fiber_manual_record_rounded, size: 14, color: scheme.error),
                const SizedBox(width: 8),
                Text(
                  '錄音中  ${_formatRecordTime(_recordSeconds)}',
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: scheme.onErrorContainer,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(width: 8),
        IconButton.filled(
          icon: const Icon(Icons.arrow_upward_rounded),
          tooltip: '傳送語音',
          onPressed: () => _stopAndSendRecording(cancel: false),
        ),
      ],
    );
  }

  Widget _buildComposer() {
    final scheme = Theme.of(context).colorScheme;

    if (_isBlocked) return _buildBlockedBar();
    if (_isRecording) return _buildRecordingBar();

    final menu = _richMenu;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        if (menu != null)
          IconButton(
            icon: Icon(
              _richMenuOpen ? Icons.keyboard_rounded : Icons.grid_view_rounded,
              color: _richMenuOpen ? scheme.primary : scheme.onSurfaceVariant,
            ),
            tooltip: _richMenuOpen ? '收起選單' : (menu['chatBarText'] ?? '選單').toString(),
            onPressed: _toggleRichMenu,
          ),
        IconButton(
          icon: Icon(Icons.add_circle_outline_rounded, color: scheme.onSurfaceVariant),
          tooltip: '附件',
          onPressed: _openAttachmentSheet,
        ),
        Expanded(
          child: Container(
            decoration: BoxDecoration(
              color: scheme.surfaceContainerHighest.withValues(alpha: 0.7),
              borderRadius: BorderRadius.circular(22),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: TextField(
                    controller: _textController,
                    focusNode: _inputFocus,
                    maxLines: 5,
                    minLines: 1,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => _sendText(),
                    decoration: const InputDecoration(
                      hintText: '輸入訊息',
                      isDense: true,
                      contentPadding: EdgeInsets.fromLTRB(16, 12, 4, 12),
                      border: InputBorder.none,
                    ),
                  ),
                ),
                IconButton(
                  icon: Icon(Icons.emoji_emotions_outlined, color: scheme.onSurfaceVariant),
                  tooltip: '貼圖',
                  onPressed: _openStickerPicker,
                ),
              ],
            ),
          ),
        ),
        const SizedBox(width: 6),
        ValueListenableBuilder<TextEditingValue>(
          valueListenable: _textController,
          builder: (context, value, _) {
            final hasText = value.text.trim().isNotEmpty;
            return IconButton.filled(
              icon: Icon(hasText ? Icons.arrow_upward_rounded : Icons.mic_rounded),
              tooltip: hasText ? '傳送' : '錄製語音',
              onPressed: hasText ? _sendText : _startRecording,
            );
          },
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final palette = ChatPalette.of(context);
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      backgroundColor: palette.background,
      appBar: _buildAppBar(),
      body: Column(
        children: [
          _buildOfflineBanner(),
          Expanded(
            child: _messages.isEmpty && !_botTyping
                ? _buildEmptyState()
                : Stack(
                    children: [
                      ListView.builder(
                        controller: _scrollController,
                        padding: const EdgeInsets.only(top: 8, bottom: 12),
                        itemCount: _messages.length + (_botTyping ? 1 : 0),
                        itemBuilder: (context, index) => index < _messages.length
                            ? _buildMessageItem(index)
                            : TypingIndicator(avatarUrl: _bot.avatarUrl),
                      ),
                      _buildJumpButton(),
                    ],
                  ),
          ),
          _buildQuickReplyBar(),
          Material(
            color: scheme.surface,
            child: SafeArea(
              top: false,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _buildReplyBar(),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(4, 6, 8, 6),
                    child: _buildComposer(),
                  ),
                  if (_richMenuOpen && _richMenu != null && !_isBlocked)
                    RichMenuPanel(
                      menu: _richMenu!,
                      onAction: _handleAction,
                      onCollapse: _toggleRichMenu,
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 日期分隔標籤
class _DateDivider extends StatelessWidget {
  final String label;

  const _DateDivider({required this.label});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
          decoration: BoxDecoration(
            color: scheme.surfaceContainerHighest.withValues(alpha: 0.8),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(
            label,
            style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
          ),
        ),
      ),
    );
  }
}

/// 「以下為未讀訊息」分隔線
class _UnreadDivider extends StatelessWidget {
  const _UnreadDivider({super.key});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final line = Expanded(child: Divider(color: scheme.primary.withValues(alpha: 0.35), height: 1));
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 6),
      child: Row(
        children: [
          line,
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Text(
              '以下為未讀訊息',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: scheme.primary),
            ),
          ),
          line,
        ],
      ),
    );
  }
}

/// 附件選單中的圓形按鈕
class _AttachmentTile extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _AttachmentTile({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.14),
                borderRadius: BorderRadius.circular(18),
              ),
              child: Icon(icon, color: color, size: 28),
            ),
            const SizedBox(height: 8),
            Text(label, style: const TextStyle(fontSize: 13)),
          ],
        ),
      ),
    );
  }
}
