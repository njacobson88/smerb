import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:flutter/foundation.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:path_provider/path_provider.dart';
import 'package:uuid/uuid.dart';
import 'package:image/image.dart' as img;
import '../../storage/database/database.dart';
import 'package:drift/drift.dart' as drift;

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

  ScreenshotService({
    required this.database,
    required this.sessionId,
    required this.participantId,
  });

  /// Start capturing screenshots every second
  void startCapture(InAppWebViewController controller, {String platform = 'unknown'}) {
    _controller = controller;
    _currentPlatform = platform;

    // Capture every 1 second
    _captureTimer = Timer.periodic(const Duration(seconds: 1), (_) {
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
    print('[ScreenshotService] Stopped screenshot capture');
  }

  /// Capture a screenshot and save if it's different from the last one
  Future<void> _captureScreenshot() async {
    if (_isCapturing || _controller == null) return;

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

      // Compress to JPEG (quality 85 = excellent quality, ~75% size reduction)
      final compressedBytes = await _compressToJpeg(screenshot, quality: 85);

      // Save screenshot to file
      final file = File(filePath);
      await file.writeAsBytes(compressedBytes);

      // Calculate compression ratio for logging
      final compressionRatio = ((1 - (compressedBytes.length / screenshot.length)) * 100).toStringAsFixed(1);

      // Record in database
      final event = EventsCompanion(
        id: drift.Value(const Uuid().v4()),
        sessionId: drift.Value(sessionId),
        participantId: drift.Value(participantId),
        eventType: const drift.Value('screenshot'),
        timestamp: drift.Value(DateTime.now().toUtc()),
        platform: drift.Value(_currentPlatform),
        url: drift.Value(url?.toString()),
        data: drift.Value('{"filePath": "$filePath", "timestamp": $timestamp, "fileSize": ${compressedBytes.length}, "originalSize": ${screenshot.length}, "compressionRatio": "$compressionRatio%"}'),
      );

      await database.insertEvent(event);

      print('[ScreenshotService] Saved screenshot: $filename (${compressedBytes.length} bytes, $compressionRatio% compression)');
    } catch (e) {
      print('[ScreenshotService] Error saving screenshot: $e');
    }
  }

  /// Compress PNG screenshot to JPEG format
  Future<Uint8List> _compressToJpeg(Uint8List pngBytes, {int quality = 85}) async {
    try {
      // Decode PNG
      final image = img.decodeImage(pngBytes);
      if (image == null) {
        print('[ScreenshotService] Failed to decode PNG, using original');
        return pngBytes;
      }

      // Encode as JPEG with specified quality (1-100)
      // Quality 85 provides excellent visual quality with significant size reduction
      final jpegBytes = img.encodeJpg(image, quality: quality);

      return Uint8List.fromList(jpegBytes);
    } catch (e) {
      print('[ScreenshotService] Error compressing to JPEG: $e');
      return pngBytes; // Fallback to original PNG
    }
  }

  void dispose() {
    stopCapture();
  }
}
