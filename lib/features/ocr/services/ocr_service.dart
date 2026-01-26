import 'dart:io';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:uuid/uuid.dart';
import '../../storage/database/database.dart';
import 'package:drift/drift.dart';

/// Service for on-device OCR text extraction from screenshots
/// Uses Apple Vision framework via method channel (iOS & macOS)
class OcrService {
  static const _channel = MethodChannel('com.smerb/ocr');

  final AppDatabase database;

  bool _isProcessing = false;

  OcrService({required this.database});

  /// Process a single screenshot and extract text
  /// Returns the extracted text or null if processing failed
  Future<String?> extractTextFromImage(String imagePath) async {
    try {
      final file = File(imagePath);
      if (!await file.exists()) {
        print('[OcrService] Image file not found: $imagePath');
        return null;
      }

      final stopwatch = Stopwatch()..start();

      // Use Apple Vision framework via method channel
      final text = await _channel.invokeMethod<String>('extractText', {
        'imagePath': imagePath,
      });

      stopwatch.stop();
      print('[OcrService] Extracted ${text?.length ?? 0} chars in ${stopwatch.elapsedMilliseconds}ms');

      return text?.trim();
    } catch (e) {
      print('[OcrService] OCR extraction failed: $e');
      return null;
    }
  }

  /// Process a screenshot event and store the OCR result
  Future<OcrResult?> processScreenshotEvent(Event event) async {
    if (event.eventType != 'screenshot') {
      print('[OcrService] Event is not a screenshot: ${event.eventType}');
      return null;
    }

    try {
      // Parse event data to get file path
      final eventData = jsonDecode(event.data) as Map<String, dynamic>;
      final filePath = eventData['filePath'] as String?;

      if (filePath == null) {
        print('[OcrService] Screenshot event missing filePath');
        return null;
      }

      final stopwatch = Stopwatch()..start();

      // Extract text
      final extractedText = await extractTextFromImage(filePath);

      stopwatch.stop();

      if (extractedText == null || extractedText.isEmpty) {
        print('[OcrService] No text extracted from screenshot');
        // Still save empty result to mark as processed
      }

      final text = extractedText ?? '';
      final wordCount = text.isEmpty ? 0 : text.split(RegExp(r'\s+')).length;

      // Create OCR result
      final resultId = const Uuid().v4();
      final result = OcrResultsCompanion(
        id: Value(resultId),
        eventId: Value(event.id),
        participantId: Value(event.participantId),
        sessionId: Value(event.sessionId),
        extractedText: Value(text),
        wordCount: Value(wordCount),
        processingTimeMs: Value(stopwatch.elapsedMilliseconds),
        capturedAt: Value(event.timestamp),
      );

      await database.insertOcrResult(result);

      print('[OcrService] Saved OCR result: $wordCount words, ${stopwatch.elapsedMilliseconds}ms');

      // Return the stored result
      return database.getOcrResultForEvent(event.id);
    } catch (e) {
      print('[OcrService] Error processing screenshot: $e');
      return null;
    }
  }

  /// Process all pending screenshots (screenshots without OCR results)
  /// Returns the number of screenshots processed
  Future<int> processPendingScreenshots({int batchSize = 10}) async {
    if (_isProcessing) {
      print('[OcrService] Already processing, skipping');
      return 0;
    }

    _isProcessing = true;
    int totalProcessed = 0;

    try {
      List<Event> pendingScreenshots;

      do {
        pendingScreenshots = await database.getScreenshotsPendingOcr(limit: batchSize);

        if (pendingScreenshots.isEmpty) break;

        print('[OcrService] Processing batch of ${pendingScreenshots.length} screenshots');

        for (final event in pendingScreenshots) {
          await processScreenshotEvent(event);
          totalProcessed++;

          // Small delay to avoid overwhelming the device
          await Future.delayed(const Duration(milliseconds: 100));
        }

      } while (pendingScreenshots.length == batchSize);

      print('[OcrService] Completed processing. Total: $totalProcessed');
      return totalProcessed;

    } catch (e) {
      print('[OcrService] Error in batch processing: $e');
      rethrow;
    } finally {
      _isProcessing = false;
    }
  }

  /// Get OCR processing status
  Future<Map<String, int>> getOcrStatus() async {
    final totalOcr = await database.getOcrResultCount();
    final pendingCount = await database.getPendingOcrCount();

    return {
      'total': totalOcr,
      'pending': pendingCount,
    };
  }
}
