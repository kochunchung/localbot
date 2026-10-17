import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import '../models/join_link.dart';

/// 掃描管理後台產生的邀請 QR Code。掃到有效的邀請就回傳 QR Code 內容（字串）。
class QrScanScreen extends StatefulWidget {
  const QrScanScreen({super.key});

  @override
  State<QrScanScreen> createState() => _QrScanScreenState();
}

class _QrScanScreenState extends State<QrScanScreen> {
  final MobileScannerController _controller = MobileScannerController(
    formats: const [BarcodeFormat.qrCode],
    detectionSpeed: DetectionSpeed.noDuplicates,
  );
  bool _done = false;
  bool _invalidShown = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_done) return;
    for (final barcode in capture.barcodes) {
      final raw = barcode.rawValue;
      if (raw == null) continue;
      if (JoinInvite.parse(raw) != null) {
        _done = true;
        Navigator.pop(context, raw);
        return;
      }
    }
    if (!_invalidShown && capture.barcodes.isNotEmpty) {
      _invalidShown = true;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('這不是 LocalBot 的邀請 QR Code')),
      );
      Future.delayed(const Duration(seconds: 3), () => _invalidShown = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: const Text('掃描邀請 QR Code'),
        actions: [
          IconButton(
            icon: const Icon(Icons.flash_on_rounded),
            tooltip: '手電筒',
            onPressed: () => _controller.toggleTorch(),
          ),
        ],
      ),
      body: Stack(
        fit: StackFit.expand,
        children: [
          MobileScanner(controller: _controller, onDetect: _onDetect),
          Align(
            alignment: Alignment.bottomCenter,
            child: Container(
              width: double.infinity,
              color: Colors.black54,
              padding: const EdgeInsets.fromLTRB(24, 16, 24, 32),
              child: const Text(
                '把相機對準管理後台上的邀請 QR Code',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.white, fontSize: 15),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
