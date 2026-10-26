import 'dart:io';
import 'dart:async';
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

  /// Upper bound for one native recognition call.
  static const Duration ocrTimeout = Duration(seconds: 20);

  /// Events that could not be processed this session (dedup original not
  /// available yet, native call timed out, ...) with their attempt count.
  /// They are skipped for the rest of the batch loop so they cannot sit at the
  /// head of the oldest-first queue and starve everything behind them; after
  /// [maxDeferrals] an empty result is recorded so the queue moves on for good.
  final Map<String, int> _deferred = {};
  static const int maxDeferrals = 3;

  OcrService({required this.database});

  Future<void> _recordEmptyResult(Event event, String reason) async {
    await database.insertOcrResult(OcrResultsCompanion(
      id: Value(const Uuid().v4()),
      eventId: Value(event.id),
      participantId: Value(event.participantId),
      sessionId: Value(event.sessionId),
      extractedText: const Value(''),
      wordCount: const Value(0),
      processingTimeMs: const Value(-1),  // sentinel: not actually recognised
      capturedAt: Value(event.timestamp),
    ));
    print('[OcrService] Recorded empty OCR for ${event.id}: $reason');
  }

  /// Returns null to mean "try again later"; bumps the deferral count and,
  /// once exhausted, records an empty result instead so the queue advances.
  Future<OcrResult?> _defer(Event event, String reason) async {
    final n = (_deferred[event.id] ?? 0) + 1;
    _deferred[event.id] = n;
    if (n >= maxDeferrals) {
      _deferred.remove(event.id);
      await _recordEmptyResult(event, '$reason (gave up after $n attempts)');
      return database.getOcrResultForEvent(event.id);
    }
    print('[OcrService] Deferring ${event.id} ($reason, attempt $n)');
    return null;
  }

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
      // Hang guard: a native recognizer that never calls back would otherwise
      // freeze this await — and with it the whole sync cycle — for the rest of
      // the session.
      final text = await _channel.invokeMethod<String>('extractText', {
        'imagePath': imagePath,
      }).timeout(ocrTimeout);

      stopwatch.stop();
      print('[OcrService] Extracted ${text?.length ?? 0} chars in ${stopwatch.elapsedMilliseconds}ms');

      return text?.trim();
    } on TimeoutException {
      print('[OcrService] OCR timed out after ${ocrTimeout.inSeconds}s: $imagePath');
      rethrow; // caller defers the event rather than recording empty text
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
        // Nothing can ever be recognised for this row; do not let it sit at
        // the head of the queue.
        await _recordEmptyResult(event, 'event has no filePath');
        return database.getOcrResultForEvent(event.id);
      }

      // Deduped screenshot: identical bytes → identical text. Copy the
      // original event's OCR result instead of re-running OCR (and the
      // shared file may already have been uploaded and deleted).
      final dedupOfEventId = eventData['dedupOfEventId'] as String?;
      if (dedupOfEventId != null) {
        final original = await database.getOcrResultForEvent(dedupOfEventId);
        if (original != null) {
          final result = OcrResultsCompanion(
            id: Value(const Uuid().v4()),
            eventId: Value(event.id),
            participantId: Value(event.participantId),
            sessionId: Value(event.sessionId),
            extractedText: Value(original.extractedText),
            wordCount: Value(original.wordCount),
            processingTimeMs: const Value(0),
            capturedAt: Value(event.timestamp),
          );
          await database.insertOcrResult(result);
          print('[OcrService] Copied OCR from deduped original $dedupOfEventId');
          return database.getOcrResultForEvent(event.id);
        }
        // Original OCR not ready yet. If the shared file is already gone
        // (uploaded + deleted), saving an empty result now would be permanent —
        // return null so this event is retried after the original's OCR lands.
        if (!File(filePath).existsSync()) {
          // The original's text (if any) lives in Firestore under
          // dedupOfEventId; the backend resolves it from there.
          return _defer(event, 'dedup original OCR pending and file gone');
        }
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

      // If the event already synced before OCR ran, the upload path deliberately
      // left the file on disk for us. Now that OCR is done, the local file is no
      // longer needed (image is in Storage, text is extracted) — delete it.
      // dedupOfEventId is null here (handled above), so this event owns the file.
      if (event.synced) {
        try {
          await File(filePath).delete();
        } catch (e) {
          print('[OcrService] Could not delete post-OCR file: $e');
        }
      }

      // Return the stored result
      return database.getOcrResultForEvent(event.id);
    } catch (e) {
      print('[OcrService] Error processing screenshot: $e');
      return _defer(event, 'error: $e');
    }
  }

  /// Process all pending screenshots (screenshots without OCR results)
  /// Returns the number of screenshots processed
  ///
  /// [maxItems] bounds one call. The background sync cycle used to drain the
  /// whole backlog here before uploading or sweeping — on a device with
  /// thousands of pending screenshots that is tens of minutes during which
  /// nothing else in the cycle runs (2026-10-21).
  Future<int> processPendingScreenshots({int batchSize = 10, int? maxItems}) async {
    if (_isProcessing) {
      print('[OcrService] Already processing, skipping');
      return 0;
    }

    _isProcessing = true;
    int totalProcessed = 0;

    try {
      List<Event> pendingScreenshots;

      do {
        pendingScreenshots = await database.getScreenshotsPendingOcr(
            limit: batchSize, excludeIds: _deferred.keys.toList());

        if (pendingScreenshots.isEmpty) break;

        print('[OcrService] Processing batch of ${pendingScreenshots.length} screenshots');

        for (final event in pendingScreenshots) {
          await processScreenshotEvent(event);
          totalProcessed++;

          // Small delay to avoid overwhelming the device
          await Future.delayed(const Duration(milliseconds: 100));
        }

      } while (pendingScreenshots.length == batchSize &&
          (maxItems == null || totalProcessed < maxItems));

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
