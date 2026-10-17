import 'dart:io';

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

/// 全螢幕影片播放（支援網址與本機檔案）。
class VideoPlayerScreen extends StatefulWidget {
  final String url;

  const VideoPlayerScreen({super.key, required this.url});

  @override
  State<VideoPlayerScreen> createState() => _VideoPlayerScreenState();
}

class _VideoPlayerScreenState extends State<VideoPlayerScreen> {
  late final VideoPlayerController _controller;
  bool _failed = false;

  bool get _isLocal => widget.url.startsWith('/') || widget.url.startsWith('file://');

  @override
  void initState() {
    super.initState();
    _controller = _isLocal
        ? VideoPlayerController.file(File(widget.url.replaceFirst('file://', '')))
        : VideoPlayerController.networkUrl(Uri.parse(widget.url));
    _init();
  }

  Future<void> _init() async {
    try {
      await _controller.initialize();
      if (!mounted) return;
      setState(() {});
      await _controller.play();
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  static String _fmt(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return d.inHours > 0 ? '${d.inHours}:$m:$s' : '$m:$s';
  }

  void _togglePlay() {
    final value = _controller.value;
    if (value.isPlaying) {
      _controller.pause();
    } else {
      if (value.position >= value.duration) {
        _controller.seekTo(Duration.zero);
      }
      _controller.play();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
      ),
      body: SafeArea(
        child: _failed
            ? const Center(
                child: Text('無法播放這部影片', style: TextStyle(color: Colors.white70)),
              )
            : ValueListenableBuilder<VideoPlayerValue>(
                valueListenable: _controller,
                builder: (context, value, _) {
                  if (!value.isInitialized) {
                    return const Center(
                      child: CircularProgressIndicator(color: Colors.white),
                    );
                  }
                  return Column(
                    children: [
                      Expanded(
                        child: GestureDetector(
                          onTap: _togglePlay,
                          child: Center(
                            child: AspectRatio(
                              aspectRatio: value.aspectRatio,
                              child: Stack(
                                alignment: Alignment.center,
                                children: [
                                  VideoPlayer(_controller),
                                  if (!value.isPlaying)
                                    const Icon(
                                      Icons.play_circle_fill_rounded,
                                      size: 72,
                                      color: Colors.white70,
                                    ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                        child: Column(
                          children: [
                            VideoProgressIndicator(
                              _controller,
                              allowScrubbing: true,
                              colors: VideoProgressColors(
                                playedColor: Theme.of(context).colorScheme.primary,
                              ),
                            ),
                            const SizedBox(height: 8),
                            Row(
                              children: [
                                IconButton(
                                  icon: Icon(
                                    value.isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded,
                                    color: Colors.white,
                                  ),
                                  tooltip: value.isPlaying ? '暫停' : '播放',
                                  onPressed: _togglePlay,
                                ),
                                Text(
                                  '${_fmt(value.position)} / ${_fmt(value.duration)}',
                                  style: const TextStyle(color: Colors.white70),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  );
                },
              ),
      ),
    );
  }
}
