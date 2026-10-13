import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import '../config.dart';
import '../theme/app_theme.dart';

/// Interactive Global Map Location Picker Screen
class LocationPickerScreen extends StatefulWidget {
  final double? initialLat;
  final double? initialLng;

  const LocationPickerScreen({
    super.key,
    this.initialLat,
    this.initialLng,
  });

  @override
  State<LocationPickerScreen> createState() => _LocationPickerScreenState();
}

class _LocationPickerScreenState extends State<LocationPickerScreen> {
  final MapController _mapController = MapController();
  final TextEditingController _titleController = TextEditingController();
  final TextEditingController _addressController = TextEditingController();

  LatLng _selectedPosition = const LatLng(25.0339, 121.5644); // Default Taipei 101
  bool _isLoadingGps = false;
  bool _isGeocoding = false;
  Timer? _debounceTimer;

  final List<Map<String, dynamic>> _quickSpots = [
    {'name': '目前定位', 'icon': Icons.my_location, 'isGps': true},
    {'name': '台北 101', 'lat': 25.033964, 'lng': 121.564468, 'addr': '台北市信義區信義路五段7號'},
    {'name': '台北車站', 'lat': 25.0478, 'lng': 121.5170, 'addr': '台北市中正區北平西路3號'},
    {'name': '板橋車站', 'lat': 25.0135, 'lng': 121.4645, 'addr': '新北市板橋區縣民大道二段7號'},
    {'name': '台中歌劇院', 'lat': 24.1627, 'lng': 120.6405, 'addr': '台中市西屯區惠來路二段101號'},
    {'name': '高雄愛河', 'lat': 22.6208, 'lng': 120.2872, 'addr': '高雄市鹽埕區真愛路1號'},
    {'name': '東京鐵塔', 'lat': 35.658581, 'lng': 139.745438, 'addr': '東京都港區芝公園4丁目2-8'},
    {'name': '巴黎鐵塔', 'lat': 48.858370, 'lng': 2.294481, 'addr': 'Champ de Mars, 5 Av. Anatole France, Paris'},
    {'name': '紐約時代廣場', 'lat': 40.758896, 'lng': -73.985130, 'addr': 'Manhattan, NY 10036, USA'},
  ];

  @override
  void initState() {
    super.initState();
    if (widget.initialLat != null && widget.initialLng != null) {
      _selectedPosition = LatLng(widget.initialLat!, widget.initialLng!);
    }
    _titleController.text = '選取位置';
    _addressController.text = '正在取得地址資訊...';

    // Auto locate device GPS on startup
    _locateDevice(moveToLocation: true);
  }

  @override
  void dispose() {
    _debounceTimer?.cancel();
    _titleController.dispose();
    _addressController.dispose();
    super.dispose();
  }

  /// Request GPS permission and locate device
  Future<void> _locateDevice({bool moveToLocation = true}) async {
    setState(() => _isLoadingGps = true);

    try {
      bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('請開啟手機 GPS 定位服務')),
          );
        }
        setState(() => _isLoadingGps = false);
        _reverseGeocode(_selectedPosition);
        return;
      }

      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
        if (permission == LocationPermission.denied) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('未取得 GPS 定位權限，使用預設位置')),
            );
          }
          setState(() => _isLoadingGps = false);
          _reverseGeocode(_selectedPosition);
          return;
        }
      }

      if (permission == LocationPermission.deniedForever) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('定位權限被永久拒絕，請至系統設定中開啟')),
          );
        }
        setState(() => _isLoadingGps = false);
        _reverseGeocode(_selectedPosition);
        return;
      }

      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high),
      ).timeout(const Duration(seconds: 8));

      final gpsLatLng = LatLng(position.latitude, position.longitude);

      if (mounted) {
        setState(() {
          _selectedPosition = gpsLatLng;
          _isLoadingGps = false;
        });

        if (moveToLocation) {
          _mapController.move(gpsLatLng, 16.0);
        }

        _reverseGeocode(gpsLatLng);
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoadingGps = false);
        _reverseGeocode(_selectedPosition);
      }
    }
  }

  /// Reverse geocode coordinates to street address via OpenStreetMap Nominatim
  Future<void> _reverseGeocode(LatLng latLng) async {
    _debounceTimer?.cancel();
    _debounceTimer = Timer(const Duration(milliseconds: 500), () async {
      if (!mounted) return;
      setState(() => _isGeocoding = true);

      try {
        final url = Uri.parse(
          'https://nominatim.openstreetmap.org/reverse?format=json&lat=${latLng.latitude}&lon=${latLng.longitude}&zoom=18&addressdetails=1&accept-language=zh-TW,en',
        );

        final res = await http.get(
          url,
          headers: {'User-Agent': AppConfig.nominatimUserAgent},
        ).timeout(const Duration(seconds: 5));

        if (res.statusCode == 200) {
          final data = jsonDecode(utf8.decode(res.bodyBytes));
          final displayName = data['display_name'] ?? '';
          final addressMap = data['address'] ?? {};

          String title = data['name'] ??
              addressMap['road'] ??
              addressMap['suburb'] ??
              addressMap['city'] ??
              '目前選取位置';

          if (title.isEmpty) {
            title = '選取位置';
          }

          if (mounted) {
            setState(() {
              _titleController.text = title;
              _addressController.text = displayName.isNotEmpty
                  ? displayName
                  : '${latLng.latitude.toStringAsFixed(5)}, ${latLng.longitude.toStringAsFixed(5)}';
              _isGeocoding = false;
            });
          }
          return;
        }
      } catch (_) {}

      if (mounted) {
        setState(() {
          _titleController.text = '選取座標位置';
          _addressController.text =
              '緯度: ${latLng.latitude.toStringAsFixed(5)}, 經度: ${latLng.longitude.toStringAsFixed(5)}';
          _isGeocoding = false;
        });
      }
    });
  }

  void _onPositionChanged(LatLng newPos) {
    setState(() {
      _selectedPosition = newPos;
    });
    _reverseGeocode(newPos);
  }

  void _confirmAndSend() {
    final title = _titleController.text.trim();
    final address = _addressController.text.trim();

    Navigator.pop(context, {
      'title': title.isNotEmpty ? title : '選取位置',
      'address': address.isNotEmpty ? address : '${_selectedPosition.latitude}, ${_selectedPosition.longitude}',
      'latitude': _selectedPosition.latitude,
      'longitude': _selectedPosition.longitude,
    });
  }

  @override
  Widget build(BuildContext context) {
    // 地圖畫面固定使用淺色主題，確保地圖與面板文字清楚可讀
    return Theme(
      data: AppTheme.light(),
      child: Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        title: const Text(
          '選擇分享位置 (全球地圖)',
          style: TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
        ),
        actions: [
          if (_isLoadingGps)
            const Center(
              child: Padding(
                padding: EdgeInsets.symmetric(horizontal: 16),
                child: SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(color: AppTheme.brandSeed, strokeWidth: 2),
                ),
              ),
            )
          else
            IconButton(
              icon: const Icon(Icons.my_location),
              tooltip: '定位目前位置',
              onPressed: () => _locateDevice(moveToLocation: true),
            ),
        ],
      ),
      body: Stack(
        children: [
          // 1. Interactive Map Layer
          FlutterMap(
            mapController: _mapController,
            options: MapOptions(
              initialCenter: _selectedPosition,
              initialZoom: 15.5,
              minZoom: 2.0,
              maxZoom: 18.5,
              onTap: (_, latLng) {
                _onPositionChanged(latLng);
              },
              onPositionChanged: (pos, hasGesture) {
                if (hasGesture) {
                  _onPositionChanged(pos.center);
                }
              },
            ),
            children: [
              TileLayer(
                urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                userAgentPackageName: 'com.example.localbot_app',
                maxZoom: 19,
              ),
              MarkerLayer(
                markers: [
                  Marker(
                    point: _selectedPosition,
                    width: 50,
                    height: 50,
                    alignment: Alignment.topCenter,
                    child: const Icon(
                      Icons.location_on,
                      color: Colors.redAccent,
                      size: 46,
                    ),
                  ),
                ],
              ),
            ],
          ),

          // 2. Top Quick City/Spot Jump Bar
          Positioned(
            top: 10,
            left: 10,
            right: 10,
            child: SizedBox(
              height: 38,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: _quickSpots.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (context, index) {
                  final spot = _quickSpots[index];
                  final isGps = spot['isGps'] == true;

                  return ActionChip(
                    backgroundColor: Colors.white.withValues(alpha: 0.92),
                    elevation: 3,
                    shadowColor: Colors.black26,
                    avatar: Icon(
                      isGps ? Icons.gps_fixed : Icons.place,
                      size: 16,
                      color: isGps ? Colors.blue : AppTheme.brandSeed,
                    ),
                    label: Text(
                      spot['name'] as String,
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: isGps ? Colors.blue.shade800 : Colors.black87,
                      ),
                    ),
                    onPressed: () {
                      if (isGps) {
                        _locateDevice(moveToLocation: true);
                      } else {
                        final lat = spot['lat'] as double;
                        final lng = spot['lng'] as double;
                        final latLng = LatLng(lat, lng);
                        setState(() {
                          _selectedPosition = latLng;
                          _titleController.text = spot['name'] as String;
                          _addressController.text = spot['addr'] as String;
                        });
                        _mapController.move(latLng, 16.0);
                      }
                    },
                  );
                },
              ),
            ),
          ),

          // 3. Center Guide Pin (when user drags map)
          Center(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 24),
              child: Icon(
                Icons.add,
                size: 20,
                color: Colors.black.withValues(alpha: 0.4),
              ),
            ),
          ),

          // 4. Bottom Location Detail Card & Send Button
          Positioned(
            bottom: 0,
            left: 0,
            right: 0,
            child: Container(
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.18),
                    blurRadius: 10,
                    offset: const Offset(0, -2),
                  ),
                ],
              ),
              padding: const EdgeInsets.fromLTRB(18, 14, 18, 18),
              child: SafeArea(
                top: false,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Handle bar
                    Center(
                      child: Container(
                        width: 36,
                        height: 4,
                        decoration: BoxDecoration(
                          color: Colors.grey.shade300,
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),

                    // Title with editing support
                    Row(
                      children: [
                        const Icon(Icons.location_on, color: AppTheme.brandSeed, size: 20),
                        const SizedBox(width: 6),
                        Expanded(
                          child: TextField(
                            controller: _titleController,
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                            ),
                            decoration: const InputDecoration(
                              isDense: true,
                              contentPadding: EdgeInsets.zero,
                              border: InputBorder.none,
                              hintText: '地點名稱',
                            ),
                          ),
                        ),
                        if (_isGeocoding)
                          const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(strokeWidth: 1.5),
                          ),
                      ],
                    ),
                    const SizedBox(height: 4),

                    // Address
                    TextField(
                      controller: _addressController,
                      maxLines: 2,
                      minLines: 1,
                      style: TextStyle(fontSize: 12, color: Colors.grey.shade700),
                      decoration: const InputDecoration(
                        isDense: true,
                        contentPadding: EdgeInsets.zero,
                        border: InputBorder.none,
                        hintText: '詳細地址',
                      ),
                    ),
                    const SizedBox(height: 6),

                    // Coordinate tag
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: Colors.grey.shade100,
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            '座標: ${_selectedPosition.latitude.toStringAsFixed(6)}, ${_selectedPosition.longitude.toStringAsFixed(6)}',
                            style: TextStyle(
                              fontSize: 11,
                              color: Colors.grey.shade600,
                              fontFamily: 'monospace',
                            ),
                          ),
                        ),
                        const Spacer(),
                        Text(
                          '可在地圖任意點選或拖曳',
                          style: TextStyle(fontSize: 11, color: Colors.grey.shade500),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),

                    // Send Button
                    SizedBox(
                      width: double.infinity,
                      height: 48,
                      child: ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.brandSeed,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14),
                          ),
                          elevation: 2,
                        ),
                        icon: const Icon(Icons.send_rounded, size: 20),
                        label: const Text(
                          '分享此位置',
                          style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                        ),
                        onPressed: _confirmAndSend,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
      ),
    );
  }
}
