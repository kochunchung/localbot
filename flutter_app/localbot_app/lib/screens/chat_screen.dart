import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';

import '../models/message.dart';
import '../services/api_service.dart';
import '../services/auth_service.dart';
import '../services/database_service.dart';
import '../services/socket_service.dart';
import '../widgets/chat_bubble.dart';
import '../theme/app_theme.dart';
import '../widgets/bot_avatar.dart';
import '../widgets/sticker_picker.dart';
import 'settings_screen.dart';
import 'location_picker_screen.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final AuthService _auth = AuthService();
  final ApiService _api = ApiService();
  final DatabaseService _db = DatabaseService();
  final SocketService _socket = SocketService();
  final ImagePicker _picker = ImagePicker();
  final AudioRecorder _audioRecorder = AudioRecorder();

  final List<ChatMessage> _messages = [];
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  StreamSubscription? _messageSub;
  StreamSubscription? _stateSub;
  SocketConnectionState _connectionState = SocketConnectionState.disconnected;

  bool _isRecording = false;
  Timer? _recordTimer;
  int _recordSeconds = 0;
  String? _dismissedQuickReplyMsgId;

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
    await _auth.init();
    await _loadLocalMessages();

    // Register with server in background
    _auth.registerWithServer();

    // Setup Socket.IO listeners
    _connectionState = _socket.connectionState;
    _stateSub = _socket.onStateChanged.listen((state) {
      if (mounted) {
        setState(() => _connectionState = state);
      }
    });

    _messageSub = _socket.onMessageReceived.listen((message) {
      _addIncomingMessage(message);
    });

    _socket.connect();
  }

  @override
  void dispose() {
    _messageSub?.cancel();
    _stateSub?.cancel();
    _recordTimer?.cancel();
    _audioRecorder.dispose();
    _textController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadLocalMessages() async {
    final localMsgs = await _db.getMessages(limit: 100);
    if (mounted) {
      setState(() {
        _messages.clear();
        _messages.addAll(localMsgs);
        _dismissedQuickReplyMsgId = null;
      });
      _scrollToBottom();
    }
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

  Future<void> _addIncomingMessage(ChatMessage message) async {
    await _db.saveMessage(message);
    if (mounted) {
      setState(() {
        _messages.add(message);
        _dismissedQuickReplyMsgId = null;
      });
      _scrollToBottom();
    }
  }

  // ==========================================================================
  // Sending Actions
  // ==========================================================================

  Future<void> _sendText() async {
    final text = _textController.text.trim();
    if (text.isEmpty) return;

    _textController.clear();

    final optimisticMsg = ChatMessage(
      id: 'local_${DateTime.now().millisecondsSinceEpoch}',
      userId: _auth.userId,
      isUser: true,
      messageType: 'text',
      content: {'text': text},
      timestamp: DateTime.now(),
      status: 'sending',
    );

    setState(() {
      _messages.add(optimisticMsg);
    });
    _scrollToBottom();

    final resultMsg = await _api.sendTextMessage(text);

    if (resultMsg != null) {
      await _db.saveMessage(resultMsg);
      setState(() {
        final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
        if (idx != -1) {
          _messages[idx] = resultMsg;
        }
      });
    } else {
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

      final sentMsg = await _api.uploadAndSendMedia(imageFile, 'image');
      if (sentMsg != null) {
        await _db.saveMessage(sentMsg);
        setState(() {
          final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
          if (idx != -1) {
            _messages[idx] = sentMsg;
          }
        });
      } else {
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

    setState(() {
      _isRecording = false;
    });

    if (cancel || path == null) return;

    final durationMs = _recordSeconds * 1000;
    final audioFile = File(path);

    final optimisticMsg = ChatMessage(
      id: 'local_audio_${DateTime.now().millisecondsSinceEpoch}',
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

    final sentMsg = await _api.uploadAndSendMedia(audioFile, 'audio', duration: durationMs);
    if (sentMsg != null) {
      await _db.saveMessage(sentMsg);
      setState(() {
        final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
        if (idx != -1) {
          _messages[idx] = sentMsg;
        }
      });
    } else {
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
      title: title,
      address: address,
      latitude: latitude,
      longitude: longitude,
    );

    if (sentMsg != null) {
      await _db.saveMessage(sentMsg);
      setState(() {
        final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
        if (idx != -1) {
          _messages[idx] = sentMsg;
        }
      });
    } else {
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

          final sentMsg = await _api.sendSticker(packageId, stickerId);
          if (sentMsg != null) {
            await _db.saveMessage(sentMsg);
            setState(() {
              final idx = _messages.indexWhere((m) => m.id == optimisticMsg.id);
              if (idx != -1) {
                _messages[idx] = sentMsg;
              }
            });
          } else {
            setState(() {
              optimisticMsg.status = 'failed';
            });
          }
        },
      ),
    );
  }

  void _handleAction(Map<String, dynamic> action) {
    setState(() {
      if (_messages.isNotEmpty) {
        _dismissedQuickReplyMsgId = _messages.last.id;
      }
    });

    final type = action['type'];
    if (type == 'postback') {
      final data = action['data'] ?? '';
      final displayText = action['displayText'] ?? action['label'];

      if (displayText != null && displayText.toString().isNotEmpty) {
        // Optimistically show user choice in chat
        final echoMsg = ChatMessage(
          id: 'pb_echo_${DateTime.now().millisecondsSinceEpoch}',
          userId: _auth.userId,
          isUser: true,
          messageType: 'text',
          content: {'text': displayText},
          timestamp: DateTime.now(),
        );
        setState(() {
          _messages.add(echoMsg);
        });
        _scrollToBottom();
      }

      _api.sendPostback(data, displayText: displayText);
    } else if (type == 'message') {
      final text = action['text'] ?? action['label'] ?? '';
      if (text.isNotEmpty) {
        _textController.text = text;
        _sendText();
      }
    } else if (type == 'camera') {
      _pickAndSendImage(ImageSource.camera);
    } else if (type == 'cameraRoll') {
      _pickAndSendImage(ImageSource.gallery);
    } else if (type == 'location') {
      _openLocationPicker();
    }
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
    _textController.text = msg.text;
    _sendText();
  }

  Widget _buildMessageItem(int index) {
    final msg = _messages[index];
    final prev = index > 0 ? _messages[index - 1] : null;
    final next = index < _messages.length - 1 ? _messages[index + 1] : null;

    final showDate = prev == null || !_sameDay(prev.timestamp, msg.timestamp);
    final startsGroup = showDate || prev == null || !_isSameGroup(prev, msg);
    final endsGroup = next == null || !_isSameGroup(msg, next);

    final bubble = ChatBubble(
      message: msg,
      onAction: _handleAction,
      showAvatar: startsGroup,
      showMeta: endsGroup,
      onRetry: msg.isUser && msg.messageType == 'text' ? () => _retryMessage(msg) : null,
    );

    if (!showDate) return bubble;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [_DateDivider(label: _dateLabel(msg.timestamp)), bubble],
    );
  }

  Widget _buildQuickReplyBar() {
    final items = _activeQuickReplyItems;
    if (items == null || items.isEmpty) {
      return const SizedBox.shrink();
    }
    final scheme = Theme.of(context).colorScheme;

    return SizedBox(
      height: 48,
      child: Row(
        children: [
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              scrollDirection: Axis.horizontal,
              itemCount: items.length,
              separatorBuilder: (_, __) => const SizedBox(width: 8),
              itemBuilder: (context, index) {
                final item = items[index];
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
              },
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
              const BotAvatar(size: 38),
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
                  _auth.botName,
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
    final history = await _api.fetchHistory();
    if (!mounted) return;
    if (history.isNotEmpty) {
      for (final h in history) {
        await _db.saveMessage(h);
      }
      await _loadLocalMessages();
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(history.isEmpty ? '沒有可同步的紀錄' : '已同步 ${history.length} 則訊息')),
    );
  }

  Future<void> _openSettings() async {
    final result = await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const SettingsScreen()),
    );
    if (result == true) {
      await _loadLocalMessages();
      if (mounted) setState(() {});
    }
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
              onPressed: _openSettings,
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
            const BotAvatar(size: 72),
            const SizedBox(height: 16),
            Text(
              _auth.botName,
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
                    onPressed: () {
                      _textController.text = s;
                      _sendText();
                    },
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
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
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

    if (_isRecording) return _buildRecordingBar();

    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
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
            child: _messages.isEmpty
                ? _buildEmptyState()
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.only(top: 8, bottom: 12),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) => _buildMessageItem(index),
                  ),
          ),
          _buildQuickReplyBar(),
          Material(
            color: scheme.surface,
            child: SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(4, 6, 8, 6),
                child: _buildComposer(),
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
