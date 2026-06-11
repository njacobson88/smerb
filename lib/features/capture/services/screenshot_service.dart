import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:path_provider/path_provider.dart';
import 'package:uuid/uuid.dart';
import 'package:image/image.dart' as img;
import '../../../core/config/environment_config.dart';
import '../../storage/database/database.dart';
import '../../settings/services/pause_service.dart';
import 'package:drift/drift.dart' as drift;

/// Top-level function for isolate-based JPEG compression.
/// Must be top-level (not a method) for compute() to work.
Map<String, dynamic> _compressToJpegIsolate(Map<String, dynamic> params) {
  final pngBytes = params['pngBytes'] as Uint8List;
  final quality = params['quality'] as int;
  final maxWidth = params['maxWidth'] as int;

  Uint8List bytes;
  try {
    final image = img.decodeImage(pngBytes);
    if (image == null) {
      bytes = pngBytes;
    } else {
      img.Image processed = image;
      if (image.width > maxWidth) {
        processed = img.copyResize(image, width: maxWidth);
      }
      bytes = Uint8List.fromList(img.encodeJpg(processed, quality: quality));
    }
  } catch (_) {
    bytes = pngBytes;
  }
  // Hash here too — sha256 on the UI isolate steals frame budget every 3s
  return {'bytes': bytes, 'hash': sha256.convert(bytes).toString()};
}

/// Service that captures screenshots every second and saves them if they've changed
class ScreenshotService {
  final AppDatabase database;
  final String sessionId;
  final String participantId;

  Timer? _captureTimer;
  Uint8List? _lastScreenshot;
  InAppWebViewController? _controller;
  bool _isCapturing = false;
  String _currentPlatform = 'unknown';
  bool _diskSpacePaused = false;
  bool _userPaused = false;
  final PauseService _pauseService = PauseService();

  /// Temporarily pause screenshot capture (e.g., 5-min privacy mode).
  bool get isUserPaused => _userPaused;
  void setUserPaused(bool paused) {
    _userPaused = paused;
    print('[ScreenshotService] User pause: $paused');
  }

  // HTML change tracking
  String? _lastHtmlHash;
  String? _lastHtmlCaptureId;

  // Screenshot dedupe: content hash → saved file path. The consecutive
  // _hasChanged check misses screens revisited later (login pages, profile
  // pages, idle screens) — ~18% of stored screenshots were exact duplicates.
  // Reusing the file path keeps the full event timeline (every viewing is
  // still recorded) while storing the identical bytes only once.
  final Map<String, ({String path, String eventId})> _jpegHashToPath = {};
  static const int _maxDedupeEntries = 5000;

  // Capture interval — 3 seconds balances data resolution vs storage/performance
  static const int captureIntervalSeconds = 3;

  // Disk space limits
  static const int maxLocalStorageMb = 2048; // 2GB cap
  int _capturesSinceLastCheck = 0;
  static const int _diskCheckInterval = 60; // Check every 60 captures (~1 min)

  ScreenshotService({
    required this.database,
    required this.sessionId,
    required this.participantId,
  });

  /// Start capturing screenshots every second
  void startCapture(InAppWebViewController controller, {String platform = 'unknown'}) {
    _controller = controller;
    _currentPlatform = platform;

    _captureTimer = Timer.periodic(Duration(seconds: captureIntervalSeconds), (_) {
      _captureScreenshot();
    });

    print('[ScreenshotService] Started screenshot capture for $platform');
  }

  /// Update the current platform
  void updatePlatform(String platform) {
    _currentPlatform = platform;
  }

  /// Stop capturing screenshots
  void stopCapture() {
    _captureTimer?.cancel();
    _captureTimer = null;
    _controller = null;
    _lastScreenshot = null;
    _lastHtmlHash = null;
    _lastHtmlCaptureId = null;
    _jpegHashToPath.clear();
    print('[ScreenshotService] Stopped screenshot capture');
  }

  /// Check disk usage of local data directories.
  /// Returns total size in bytes, or -1 if check fails.
  static Future<int> getLocalStorageBytes() async {
    try {
      final directory = await getApplicationDocumentsDirectory();
      int totalBytes = 0;

      for (final dirName in ['screenshots', 'html']) {
        final dir = Directory('${directory.path}/$dirName');
        if (await dir.exists()) {
          await for (final entity in dir.list(recursive: true, followLinks: false)) {
            if (entity is File) {
              totalBytes += await entity.length();
            }
          }
        }
      }
      return totalBytes;
    } catch (e) {
      return -1;
    }
  }

  /// Get local storage usage in MB (for display/monitoring)
  static Future<double> getLocalStorageMb() async {
    final bytes = await getLocalStorageBytes();
    if (bytes < 0) return -1;
    return bytes / (1024 * 1024);
  }

  /// Surface capture-pause status to Firestore so the study team is alerted to
  /// the data-loss risk (capture paused because the device's local cache hit
  /// its cap — usually a sign the device has been offline/unable to upload for
  /// a long time). Best-effort; never throws.
  Future<void> _reportCaptureStatus({required bool paused, required double usageMb}) async {
    try {
      await FirebaseFirestore.instance
          .collection(EnvConfig.col('participants'))
          .doc(participantId)
          .set({
        'captureDiskPaused': paused,
        'captureDiskPausedAt': paused ? FieldValue.serverTimestamp() : null,
        'captureDiskUsageMb': usageMb.round(),
        'captureStatusUpdatedAt': FieldValue.serverTimestamp(),
      }, SetOptions(merge: true));
    } catch (e) {
      print('[ScreenshotService] Could not report capture status: $e');
    }
  }

  /// Capture a screenshot and save if it's different from the last one
  Future<void> _captureScreenshot() async {
    if (_isCapturing || _controller == null) return;
    if (_userPaused || _pauseService.isPaused) return;

    // Disk-space gate. When over the cap we pause capture, but we must keep
    // RE-CHECKING so capture resumes once background sync uploads + prunes free
    // space — otherwise capture would stay dead for the whole session (silent
    // data loss). So this check runs even while paused.
    _capturesSinceLastCheck++;
    if (_capturesSinceLastCheck >= _diskCheckInterval || _diskSpacePaused) {
      _capturesSinceLastCheck = 0;
      final usageMb = await getLocalStorageMb();
      if (usageMb > 0 && usageMb >= maxLocalStorageMb) {
        if (!_diskSpacePaused) {
          _diskSpacePaused = true;
          print('[ScreenshotService] PAUSED: Local storage at ${usageMb.toStringAsFixed(0)}MB (limit: ${maxLocalStorageMb}MB)');
          _reportCaptureStatus(paused: true, usageMb: usageMb);
        }
        return;
      } else if (_diskSpacePaused && usageMb >= 0 && usageMb < maxLocalStorageMb) {
        // Space freed up — resume capture and clear the alert.
        _diskSpacePaused = false;
        print('[ScreenshotService] RESUMED: Local storage back to ${usageMb.toStringAsFixed(0)}MB');
        _reportCaptureStatus(paused: false, usageMb: usageMb);
      }
    }
    if (_diskSpacePaused) return;

    _isCapturing = true;

    try {
      // Take screenshot
      final screenshot = await _controller!.takeScreenshot();
      if (screenshot == null) {
        _isCapturing = false;
        return;
      }

      // Check if screenshot has changed
      if (_lastScreenshot != null && !_hasChanged(screenshot, _lastScreenshot!)) {
        _isCapturing = false;
        return; // No change, skip saving
      }

      // Screenshot has changed, save it
      await _saveScreenshot(screenshot);

      // Update last screenshot
      _lastScreenshot = screenshot;
    } catch (e) {
      print('[ScreenshotService] Error capturing screenshot: $e');
    } finally {
      _isCapturing = false;
    }
  }

  /// Check if two screenshots are different
  /// Uses a simple sampling approach for performance
  bool _hasChanged(Uint8List newScreenshot, Uint8List oldScreenshot) {
    // If sizes are different, they've changed
    if (newScreenshot.length != oldScreenshot.length) {
      return true;
    }

    // Sample every Nth byte to compare (for performance)
    // Sampling every 1000 bytes is fast and accurate enough
    const sampleInterval = 1000;
    int differences = 0;
    const maxDifferences = 100; // Threshold for considering it "changed"

    for (int i = 0; i < newScreenshot.length; i += sampleInterval) {
      if (newScreenshot[i] != oldScreenshot[i]) {
        differences++;
        if (differences > maxDifferences) {
          return true; // Early exit if we've found enough differences
        }
      }
    }

    return differences > maxDifferences;
  }

  /// Save screenshot to disk and record in database
  Future<void> _saveScreenshot(Uint8List screenshot) async {
    try {
      // Get current URL from controller
      final url = await _controller?.getUrl();

      // Create screenshots directory
      final directory = await getApplicationDocumentsDirectory();
      final screenshotsDir = Directory('${directory.path}/screenshots/$sessionId');
      if (!await screenshotsDir.exists()) {
        await screenshotsDir.create(recursive: true);
      }

      // Generate unique filename
      final timestamp = DateTime.now().millisecondsSinceEpoch;
      final filename = 'screenshot_$timestamp.jpg'; // Changed to .jpg
      String filePath = '${screenshotsDir.path}/$filename';

      // Downscale from Retina resolution and compress to JPEG (hash computed
      // on the same background isolate)
      final compressed = await _compressToJpeg(screenshot, quality: 70);
      final compressedBytes = compressed.bytes;

      // Dedupe: identical bytes already saved this session → reuse that file.
      // The event below is still recorded, so the timeline is fully preserved.
      final contentHash = compressed.hash;
      final existing = _jpegHashToPath[contentHash];
      final isDuplicate = existing != null;
      final eventId = const Uuid().v4();

      if (isDuplicate) {
        filePath = existing.path;
      } else {
        final file = File(filePath);
        await file.writeAsBytes(compressedBytes);
        if (_jpegHashToPath.length >= _maxDedupeEntries) {
          _jpegHashToPath.remove(_jpegHashToPath.keys.first);
        }
        _jpegHashToPath[contentHash] = (path: filePath, eventId: eventId);
      }

      // Calculate compression ratio for logging
      final compressionRatio = ((1 - (compressedBytes.length / screenshot.length)) * 100).toStringAsFixed(1);

      // Record in database
      final dedupField = isDuplicate ? ', "dedupOfEventId": "${existing.eventId}"' : '';
      final event = EventsCompanion(
        id: drift.Value(eventId),
        sessionId: drift.Value(sessionId),
        participantId: drift.Value(participantId),
        eventType: const drift.Value('screenshot'),
        timestamp: drift.Value(DateTime.now()),  // Local time for participant
        platform: drift.Value(_currentPlatform),
        url: drift.Value(url?.toString()),
        data: drift.Value('{"filePath": "$filePath", "timestamp": $timestamp, "fileSize": ${compressedBytes.length}, "originalSize": ${screenshot.length}, "compressionRatio": "$compressionRatio%", "contentHash": "$contentHash", "dedup": $isDuplicate$dedupField}'),
      );

      await database.insertEvent(event);

      print('[ScreenshotService] Saved screenshot: ${filePath.split('/').last} '
          '(${compressedBytes.length} bytes, $compressionRatio% compression'
          '${isDuplicate ? ", deduped" : ""})');

      // Capture HTML from the page
      await _captureHtml(
        eventId: eventId,
        url: url?.toString(),
        capturedAt: DateTime.now(),  // Local time for participant
      );
    } catch (e) {
      print('[ScreenshotService] Error saving screenshot: $e');
    }
  }

  /// Downscale and compress PNG screenshot to JPEG format on a background isolate.
  /// This prevents UI jank since image decoding/encoding is CPU-intensive.
  static const int _maxScreenshotWidth = 750;

  Future<({Uint8List bytes, String hash})> _compressToJpeg(Uint8List pngBytes, {int quality = 70}) async {
    try {
      final r = await compute(_compressToJpegIsolate, {
        'pngBytes': pngBytes,
        'quality': quality,
        'maxWidth': _maxScreenshotWidth,
      });
      return (bytes: r['bytes'] as Uint8List, hash: r['hash'] as String);
    } catch (e) {
      print('[ScreenshotService] Error compressing to JPEG: $e');
      return (bytes: pngBytes, hash: sha256.convert(pngBytes).toString());
    }
  }

  /// Capture HTML from the current page, storing only when it changes
  Future<void> _captureHtml({
    required String eventId,
    required String? url,
    required DateTime capturedAt,
  }) async {
    try {
      if (_controller == null) return;

      // Extract full page HTML
      final htmlResult = await _controller!.evaluateJavascript(
        source: 'document.documentElement.outerHTML',
      );

      if (htmlResult == null || htmlResult is! String || htmlResult.isEmpty) {
        return;
      }

      final html = htmlResult;

      // Compute SHA-256 hash
      final htmlHash = sha256.convert(utf8.encode(html)).toString();

      if (_lastHtmlHash != null && htmlHash == _lastHtmlHash) {
        // HTML unchanged - just log the status
        final statusLog = HtmlStatusLogsCompanion(
          id: drift.Value(const Uuid().v4()),
          eventId: drift.Value(eventId),
          participantId: drift.Value(participantId),
          sessionId: drift.Value(sessionId),
          htmlChanged: const drift.Value(false),
          htmlCaptureId: drift.Value(_lastHtmlCaptureId),
          htmlHash: drift.Value(htmlHash),
          capturedAt: drift.Value(capturedAt),
        );

        await database.insertHtmlStatusLog(statusLog);
      } else {
        // HTML changed - save the file and create a capture record
        final directory = await getApplicationDocumentsDirectory();
        final htmlDir = Directory('${directory.path}/html/$sessionId');
        if (!await htmlDir.exists()) {
          await htmlDir.create(recursive: true);
        }

        final timestamp = DateTime.now().millisecondsSinceEpoch;
        final htmlFilePath = '${htmlDir.path}/page_$timestamp.html.gz';
        final htmlFile = File(htmlFilePath);
        final compressed = gzip.encode(utf8.encode(html));
        await htmlFile.writeAsBytes(compressed);

        final captureId = const Uuid().v4();

        final capture = HtmlCapturesCompanion(
          id: drift.Value(captureId),
          eventId: drift.Value(eventId),
          participantId: drift.Value(participantId),
          sessionId: drift.Value(sessionId),
          htmlHash: drift.Value(htmlHash),
          filePath: drift.Value(htmlFilePath),
          charCount: drift.Value(html.length),
          url: drift.Value(url),
          platform: drift.Value(_currentPlatform),
          capturedAt: drift.Value(capturedAt),
        );

        await database.insertHtmlCapture(capture);

        final statusLog = HtmlStatusLogsCompanion(
          id: drift.Value(const Uuid().v4()),
          eventId: drift.Value(eventId),
          participantId: drift.Value(participantId),
          sessionId: drift.Value(sessionId),
          htmlChanged: const drift.Value(true),
          htmlCaptureId: drift.Value(captureId),
          htmlHash: drift.Value(htmlHash),
          capturedAt: drift.Value(capturedAt),
        );

        await database.insertHtmlStatusLog(statusLog);

        _lastHtmlCaptureId = captureId;

        print('[ScreenshotService] Saved HTML: ${html.length} chars, hash: ${htmlHash.substring(0, 8)}...');
      }

      _lastHtmlHash = htmlHash;
    } catch (e) {
      print('[ScreenshotService] Error capturing HTML: $e');
    }
  }

  void dispose() {
    stopCapture();
  }
}
