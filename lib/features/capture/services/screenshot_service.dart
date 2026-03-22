import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:path_provider/path_provider.dart';
import 'package:uuid/uuid.dart';
import 'package:image/image.dart' as img;
import '../../storage/database/database.dart';
import 'package:drift/drift.dart' as drift;

/// Top-level function for isolate-based JPEG compression.
/// Must be top-level (not a method) for compute() to work.
Uint8List _compressToJpegIsolate(Map<String, dynamic> params) {
  final pngBytes = params['pngBytes'] as Uint8List;
  final quality = params['quality'] as int;
  final maxWidth = params['maxWidth'] as int;

  try {
    final image = img.decodeImage(pngBytes);
    if (image == null) return pngBytes;

    img.Image processed = image;
    if (image.width > maxWidth) {
      processed = img.copyResize(image, width: maxWidth);
    }

    final jpegBytes = img.encodeJpg(processed, quality: quality);
    return Uint8List.fromList(jpegBytes);
  } catch (_) {
    return pngBytes;
  }
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

  // HTML change tracking
  String? _lastHtmlHash;
  String? _lastHtmlCaptureId;

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

  /// Capture a screenshot and save if it's different from the last one
  Future<void> _captureScreenshot() async {
    if (_isCapturing || _controller == null) return;
    if (_diskSpacePaused) return;

    // Periodically check disk space
    _capturesSinceLastCheck++;
    if (_capturesSinceLastCheck >= _diskCheckInterval) {
      _capturesSinceLastCheck = 0;
      final usageMb = await getLocalStorageMb();
      if (usageMb > 0 && usageMb >= maxLocalStorageMb) {
        _diskSpacePaused = true;
        print('[ScreenshotService] PAUSED: Local storage at ${usageMb.toStringAsFixed(0)}MB (limit: ${maxLocalStorageMb}MB)');
        return;
      }
    }

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
      final filePath = '${screenshotsDir.path}/$filename';

      // Downscale from Retina resolution and compress to JPEG
      final compressedBytes = await _compressToJpeg(screenshot, quality: 70);

      // Save screenshot to file
      final file = File(filePath);
      await file.writeAsBytes(compressedBytes);

      // Calculate compression ratio for logging
      final compressionRatio = ((1 - (compressedBytes.length / screenshot.length)) * 100).toStringAsFixed(1);

      // Record in database
      final eventId = const Uuid().v4();
      final event = EventsCompanion(
        id: drift.Value(eventId),
        sessionId: drift.Value(sessionId),
        participantId: drift.Value(participantId),
        eventType: const drift.Value('screenshot'),
        timestamp: drift.Value(DateTime.now()),  // Local time for participant
        platform: drift.Value(_currentPlatform),
        url: drift.Value(url?.toString()),
        data: drift.Value('{"filePath": "$filePath", "timestamp": $timestamp, "fileSize": ${compressedBytes.length}, "originalSize": ${screenshot.length}, "compressionRatio": "$compressionRatio%"}'),
      );

      await database.insertEvent(event);

      print('[ScreenshotService] Saved screenshot: $filename (${compressedBytes.length} bytes, $compressionRatio% compression)');

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

  Future<Uint8List> _compressToJpeg(Uint8List pngBytes, {int quality = 70}) async {
    try {
      return await compute(_compressToJpegIsolate, {
        'pngBytes': pngBytes,
        'quality': quality,
        'maxWidth': _maxScreenshotWidth,
      });
    } catch (e) {
      print('[ScreenshotService] Error compressing to JPEG: $e');
      return pngBytes;
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
