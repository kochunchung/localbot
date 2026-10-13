import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import '../services/api_service.dart';
import '../services/auth_service.dart';

typedef OnStickerSelected = void Function(String packageId, String stickerId);

/// Bottom sheet sticker picker.
class StickerPickerWidget extends StatefulWidget {
  final OnStickerSelected onStickerSelected;

  const StickerPickerWidget({super.key, required this.onStickerSelected});

  @override
  State<StickerPickerWidget> createState() => _StickerPickerWidgetState();
}

class _StickerPickerWidgetState extends State<StickerPickerWidget> {
  final ApiService _api = ApiService();
  final AuthService _auth = AuthService();
  List<Map<String, dynamic>> _packages = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadStickers();
  }

  Future<void> _loadStickers() async {
    final pkgs = await _api.fetchStickerPackages();
    if (mounted) {
      setState(() {
        _packages = pkgs.isNotEmpty
            ? pkgs
            : [
                {
                  'packageId': '1',
                  'name': '預設貼圖',
                  'stickers': ['1', '2', '3', '4', '5']
                }
              ];
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const SizedBox(
        height: 220,
        child: Center(child: CircularProgressIndicator()),
      );
    }

    final baseUrl = _auth.serverUrl.replaceAll(RegExp(r'/+$'), '');
    final scheme = Theme.of(context).colorScheme;

    return DefaultTabController(
      length: _packages.length,
      child: SizedBox(
        height: 300,
        child: Column(
          children: [
            const SizedBox(height: 8),
            Container(
              width: 36,
              height: 4,
              decoration: BoxDecoration(
                color: scheme.outlineVariant,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            TabBar(
              isScrollable: true,
              tabAlignment: TabAlignment.start,
              dividerColor: Colors.transparent,
              tabs: _packages
                  .map((p) => Tab(text: p['name'] ?? '貼圖包 ${p['packageId']}'))
                  .toList(),
            ),
            Expanded(
              child: TabBarView(
                children: _packages.map((pkg) {
                  final pkgId = pkg['packageId'].toString();
                  final stickers = (pkg['stickers'] as List? ?? []).map((e) => e.toString()).toList();

                  return GridView.builder(
                    padding: const EdgeInsets.all(12),
                    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 4,
                      crossAxisSpacing: 12,
                      mainAxisSpacing: 12,
                    ),
                    itemCount: stickers.length,
                    itemBuilder: (context, index) {
                      final stickerId = stickers[index];
                      final stickerUrl = '$baseUrl/stickers/$pkgId/$stickerId';

                      return InkWell(
                        onTap: () {
                          widget.onStickerSelected(pkgId, stickerId);
                          Navigator.pop(context);
                        },
                        borderRadius: BorderRadius.circular(12),
                        child: Container(
                          padding: const EdgeInsets.all(6),
                          decoration: BoxDecoration(
                            color: scheme.surfaceContainerLow,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: CachedNetworkImage(
                            imageUrl: stickerUrl,
                            fit: BoxFit.contain,
                            placeholder: (_, __) => const Center(
                              child: CircularProgressIndicator(strokeWidth: 1.5),
                            ),
                            errorWidget: (_, __, ___) => const Center(
                              child: Text('😊', style: TextStyle(fontSize: 32)),
                            ),
                          ),
                        ),
                      );
                    },
                  );
                }).toList(),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
