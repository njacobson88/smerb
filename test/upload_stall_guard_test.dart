import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:smerb_app/features/sync/services/upload_service.dart';

/// 2026-11-24: a fixed 30 s upload timeout cut off slow-but-moving uploads and
/// let a stuck one hold the sync cycle for the full 30 s. The guard now cuts
/// on "no bytes for 10 s" (or a 3-minute hard cap) instead.
void main() {
  final t0 = DateTime(2026, 11, 24, 12, 0, 0);

  group('UploadStallDetector', () {
    test('a moving upload is never stalled, however slow', () {
      final d = UploadStallDetector(startedAt: t0);
      for (var s = 1; s <= 60; s++) {
        d.progress(s * 1000, t0.add(Duration(seconds: s))); // 1 KB/s
        expect(d.stalledReason(t0.add(Duration(seconds: s))), isNull, reason: 'at ${s}s');
      }
      expect(d.bytesTransferred, 60000);
    });

    test('no bytes for the stall window -> stalled, with the byte count', () {
      final d = UploadStallDetector(startedAt: t0);
      d.progress(5000, t0.add(const Duration(seconds: 3)));
      expect(d.stalledReason(t0.add(const Duration(seconds: 12))), isNull); // 9 s since progress
      expect(d.stalledReason(t0.add(const Duration(seconds: 13))), 'no progress for 10s (5000 bytes sent)');
    });

    test('never any bytes -> stalled 10 s after start', () {
      final d = UploadStallDetector(startedAt: t0);
      expect(d.stalledReason(t0.add(const Duration(seconds: 9))), isNull);
      expect(d.stalledReason(t0.add(const Duration(seconds: 10))), startsWith('no progress for 10s'));
    });

    test('repeated identical snapshots do not count as progress', () {
      final d = UploadStallDetector(startedAt: t0);
      d.progress(100, t0.add(const Duration(seconds: 1)));
      for (var s = 2; s <= 11; s++) {
        d.progress(100, t0.add(Duration(seconds: s)));
      }
      expect(d.stalledReason(t0.add(const Duration(seconds: 11))), isNotNull);
    });

    test('hard cap stops even a moving upload', () {
      final d = UploadStallDetector(startedAt: t0, hardCap: const Duration(seconds: 30));
      for (var s = 1; s <= 29; s++) {
        d.progress(s, t0.add(Duration(seconds: s)));
      }
      expect(d.stalledReason(t0.add(const Duration(seconds: 29))), isNull);
      d.progress(30, t0.add(const Duration(seconds: 30)));
      expect(d.stalledReason(t0.add(const Duration(seconds: 30))), 'exceeded 30s (30 bytes sent)');
    });

    test('a stall is classified as a timeout for the diagnostics event', () {
      expect(UploadService.classifyHtmlError(Exception('HTML upload stalled: no progress for 10s (0 bytes sent)')),
          'timeout');
    });
  });

  group('UploadService.connectivityLabel', () {
    test('names the connection, sorted and de-duplicated', () {
      expect(UploadService.connectivityLabel([ConnectivityResult.wifi]), 'wifi');
      expect(UploadService.connectivityLabel([ConnectivityResult.mobile]), 'mobile');
      expect(UploadService.connectivityLabel([ConnectivityResult.none]), 'none');
      expect(UploadService.connectivityLabel([ConnectivityResult.vpn, ConnectivityResult.wifi, ConnectivityResult.wifi]),
          'vpn+wifi');
      expect(UploadService.connectivityLabel([ConnectivityResult.bluetooth]), 'other');
      expect(UploadService.connectivityLabel([]), 'unknown');
    });
  });
}
