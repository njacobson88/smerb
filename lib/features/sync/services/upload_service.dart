import 'dart:convert';
import 'dart:io';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_storage/firebase_storage.dart';
import '../../storage/database/database.dart';

/// Service that syncs local data to Firebase
class UploadService {
  final AppDatabase database;
  final FirebaseFirestore _firestore;
  final FirebaseStorage _storage;

  bool _isSyncing = false;
  bool _isSyncingOcr = false;
  bool _isSyncingHtml = false;
  bool _isSyncingEma = false;

  // Track screenshots uploaded for syncAll return value
  int _screenshotsUploaded = 0;

  UploadService({
    required this.database,
    FirebaseFirestore? firestore,
    FirebaseStorage? storage,
  })  : _firestore = firestore ?? FirebaseFirestore.instance,
        _storage = storage ?? FirebaseStorage.instance;

  /// Sync all unsynced events to Firebase
  /// Returns the number of events synced
  Future<int> syncEvents({int batchSize = 50}) async {
    if (_isSyncing) {
      print('[UploadService] Sync already in progress, skipping');
      return 0;
    }

    _isSyncing = true;
    int totalSynced = 0;

    try {
      // Get unsynced events in batches
      List<Event> unsyncedEvents;

      do {
        unsyncedEvents = await database.getUnsyncedEvents(limit: batchSize);

        if (unsyncedEvents.isEmpty) break;

        print('[UploadService] Processing batch of ${unsyncedEvents.length} events');

        final syncedIds = <String>[];

        for (final event in unsyncedEvents) {
          try {
            await _uploadEvent(event);
            syncedIds.add(event.id);
          } catch (e) {
            print('[UploadService] Failed to sync event ${event.id}: $e');
            // Continue with other events even if one fails
          }
        }

        // Mark successfully synced events
        if (syncedIds.isNotEmpty) {
          await database.markEventsAsSynced(syncedIds);
          totalSynced += syncedIds.length;
          print('[UploadService] Marked ${syncedIds.length} events as synced');
        }

      } while (unsyncedEvents.length == batchSize);

      print('[UploadService] Sync complete. Total synced: $totalSynced');
      return totalSynced;

    } catch (e) {
      print('[UploadService] Sync error: $e');
      rethrow;
    } finally {
      _isSyncing = false;
    }
  }

  /// Upload a single event to Firebase
  Future<void> _uploadEvent(Event event) async {
    // Parse the event data
    Map<String, dynamic> eventData;
    try {
      eventData = jsonDecode(event.data) as Map<String, dynamic>;
    } catch (e) {
      eventData = {'raw': event.data};
    }

    // Handle screenshot events specially - upload file to Storage and include OCR
    String? storageUrl;
    Map<String, dynamic>? ocrData;

    if (event.eventType == 'screenshot') {
      storageUrl = await _uploadScreenshot(event, eventData);
      if (storageUrl != null) {
        _screenshotsUploaded++;
      }

      // Get OCR result if available
      final ocrResult = await database.getOcrResultForEvent(event.id);
      if (ocrResult != null) {
        ocrData = {
          'extractedText': ocrResult.extractedText,
          'wordCount': ocrResult.wordCount,
          'processingTimeMs': ocrResult.processingTimeMs,
          'processedAt': Timestamp.fromDate(ocrResult.processedAt),
        };
      }
    }

    // Prepare Firestore document
    final docData = <String, dynamic>{
      'id': event.id,
      'sessionId': event.sessionId,
      'participantId': event.participantId,
      'eventType': event.eventType,
      'timestamp': Timestamp.fromDate(event.timestamp),
      'platform': event.platform,
      'url': event.url,
      'data': eventData,
      'createdAt': Timestamp.fromDate(event.createdAt),
      'syncedAt': FieldValue.serverTimestamp(),
    };

    // Add storage URL for screenshots
    if (storageUrl != null) {
      docData['screenshotUrl'] = storageUrl;
    }

    // Add OCR data for screenshots
    if (ocrData != null) {
      docData['ocr'] = ocrData;
    }

    // Upload to Firestore
    // Structure: participants/{participantId}/events/{eventId}
    await _firestore
        .collection('participants')
        .doc(event.participantId)
        .collection('events')
        .doc(event.id)
        .set(docData);

    print('[UploadService] Uploaded event: ${event.eventType} (${event.id})');
  }

  /// Upload screenshot file to Firebase Storage
  Future<String?> _uploadScreenshot(Event event, Map<String, dynamic> eventData) async {
    final filePath = eventData['filePath'] as String?;
    if (filePath == null) {
      print('[UploadService] Screenshot event missing filePath');
      return null;
    }

    final file = File(filePath);
    if (!await file.exists()) {
      print('[UploadService] Screenshot file not found: $filePath');
      return null;
    }

    try {
      // Upload path: screenshots/{participantId}/{sessionId}/{filename}
      final filename = filePath.split('/').last;
      final storagePath = 'screenshots/${event.participantId}/${event.sessionId}/$filename';

      final ref = _storage.ref().child(storagePath);

      // Upload with metadata
      final metadata = SettableMetadata(
        contentType: 'image/jpeg',
        customMetadata: {
          'eventId': event.id,
          'sessionId': event.sessionId,
          'participantId': event.participantId,
          'timestamp': event.timestamp.toIso8601String(),
        },
      );

      final uploadTask = await ref.putFile(file, metadata);
      final downloadUrl = await uploadTask.ref.getDownloadURL();

      print('[UploadService] Uploaded screenshot: $storagePath');

      // Optionally delete local file after successful upload
      // await file.delete();

      return downloadUrl;
    } catch (e) {
      print('[UploadService] Failed to upload screenshot: $e');
      return null;
    }
  }

  /// Sync OCR results to Firebase (updates existing events with OCR data)
  /// Returns the number of OCR results synced
  Future<int> syncOcrResults({int batchSize = 50}) async {
    if (_isSyncingOcr) {
      print('[UploadService] OCR sync already in progress, skipping');
      return 0;
    }

    _isSyncingOcr = true;
    int totalSynced = 0;

    try {
      List<OcrResult> unsyncedResults;

      do {
        unsyncedResults = await database.getUnsyncedOcrResults(limit: batchSize);

        if (unsyncedResults.isEmpty) break;

        print('[UploadService] Processing batch of ${unsyncedResults.length} OCR results');

        final syncedIds = <String>[];

        for (final result in unsyncedResults) {
          try {
            await _uploadOcrResult(result);
            syncedIds.add(result.id);
          } catch (e) {
            print('[UploadService] Failed to sync OCR result ${result.id}: $e');
          }
        }

        if (syncedIds.isNotEmpty) {
          await database.markOcrResultsAsSynced(syncedIds);
          totalSynced += syncedIds.length;
          print('[UploadService] Marked ${syncedIds.length} OCR results as synced');
        }

      } while (unsyncedResults.length == batchSize);

      print('[UploadService] OCR sync complete. Total: $totalSynced');
      return totalSynced;

    } catch (e) {
      print('[UploadService] OCR sync error: $e');
      rethrow;
    } finally {
      _isSyncingOcr = false;
    }
  }

  /// Upload a single OCR result to Firebase (updates existing event document)
  Future<void> _uploadOcrResult(OcrResult result) async {
    final ocrData = {
      'ocr': {
        'extractedText': result.extractedText,
        'wordCount': result.wordCount,
        'processingTimeMs': result.processingTimeMs,
        'processedAt': Timestamp.fromDate(result.processedAt),
        'capturedAt': Timestamp.fromDate(result.capturedAt),
      },
      'ocrSyncedAt': FieldValue.serverTimestamp(),
    };

    // Update the existing event document
    await _firestore
        .collection('participants')
        .doc(result.participantId)
        .collection('events')
        .doc(result.eventId)
        .update(ocrData);

    print('[UploadService] Updated event with OCR: ${result.eventId}');
  }

  /// Sync HTML captures to Firebase (uploads HTML files and updates event docs)
  /// Returns the number of HTML captures synced
  Future<int> syncHtmlCaptures({int batchSize = 50}) async {
    if (_isSyncingHtml) {
      print('[UploadService] HTML sync already in progress, skipping');
      return 0;
    }

    _isSyncingHtml = true;
    int totalSynced = 0;

    try {
      List<HtmlCapture> unsyncedCaptures;

      do {
        unsyncedCaptures = await database.getUnsyncedHtmlCaptures(limit: batchSize);

        if (unsyncedCaptures.isEmpty) break;

        print('[UploadService] Processing batch of ${unsyncedCaptures.length} HTML captures');

        final syncedIds = <String>[];

        for (final capture in unsyncedCaptures) {
          try {
            await _uploadHtmlCapture(capture);
            syncedIds.add(capture.id);
          } catch (e) {
            print('[UploadService] Failed to sync HTML capture ${capture.id}: $e');
          }
        }

        if (syncedIds.isNotEmpty) {
          await database.markHtmlCapturesAsSynced(syncedIds);
          totalSynced += syncedIds.length;
          print('[UploadService] Marked ${syncedIds.length} HTML captures as synced');
        }

      } while (unsyncedCaptures.length == batchSize);

      print('[UploadService] HTML capture sync complete. Total: $totalSynced');
      return totalSynced;

    } catch (e) {
      print('[UploadService] HTML capture sync error: $e');
      rethrow;
    } finally {
      _isSyncingHtml = false;
    }
  }

  /// Upload a single HTML capture to Firebase Storage and update event document
  Future<void> _uploadHtmlCapture(HtmlCapture capture) async {
    final file = File(capture.filePath);
    if (!await file.exists()) {
      print('[UploadService] HTML file not found: ${capture.filePath}');
      throw Exception('HTML file not found: ${capture.filePath}');
    }

    print('[UploadService] Uploading HTML file: ${capture.filePath} (${capture.charCount} chars)');

    // Upload HTML file to Storage
    final filename = capture.filePath.split('/').last;
    final storagePath = 'html/${capture.participantId}/${capture.sessionId}/$filename';

    final ref = _storage.ref().child(storagePath);
    final metadata = SettableMetadata(
      contentType: 'text/html',
      customMetadata: {
        'eventId': capture.eventId,
        'sessionId': capture.sessionId,
        'participantId': capture.participantId,
        'htmlHash': capture.htmlHash,
      },
    );

    final uploadTask = await ref.putFile(file, metadata);
    final downloadUrl = await uploadTask.ref.getDownloadURL();

    // Update the event document with HTML data using dot notation
    // to avoid overwriting fields set by status log sync
    await _firestore
        .collection('participants')
        .doc(capture.participantId)
        .collection('events')
        .doc(capture.eventId)
        .update({
      'html.storageUrl': downloadUrl,
      'html.charCount': capture.charCount,
      'html.hash': capture.htmlHash,
      'html.changed': true,
      'html.capturedAt': Timestamp.fromDate(capture.capturedAt),
      'htmlSyncedAt': FieldValue.serverTimestamp(),
    });

    print('[UploadService] Uploaded HTML capture: $storagePath');
  }

  /// Sync HTML status logs to Firebase (updates event docs with HTML status)
  /// Returns the number of status logs synced
  Future<int> syncHtmlStatusLogs({int batchSize = 50}) async {
    int totalSynced = 0;

    try {
      List<HtmlStatusLog> unsyncedLogs;

      do {
        unsyncedLogs = await database.getUnsyncedHtmlStatusLogs(limit: batchSize);

        if (unsyncedLogs.isEmpty) break;

        print('[UploadService] Processing batch of ${unsyncedLogs.length} HTML status logs');

        final syncedIds = <String>[];

        for (final log in unsyncedLogs) {
          try {
            await _uploadHtmlStatusLog(log);
            syncedIds.add(log.id);
          } catch (e) {
            print('[UploadService] Failed to sync HTML status log ${log.id}: $e');
          }
        }

        if (syncedIds.isNotEmpty) {
          await database.markHtmlStatusLogsSynced(syncedIds);
          totalSynced += syncedIds.length;
          print('[UploadService] Marked ${syncedIds.length} HTML status logs as synced');
        }

      } while (unsyncedLogs.length == batchSize);

      print('[UploadService] HTML status log sync complete. Total: $totalSynced');
      return totalSynced;

    } catch (e) {
      print('[UploadService] HTML status log sync error: $e');
      rethrow;
    }
  }

  /// Upload a single HTML status log to Firebase (updates existing event document)
  /// Uses dot notation to avoid overwriting storageUrl/charCount from capture sync
  Future<void> _uploadHtmlStatusLog(HtmlStatusLog log) async {
    final updates = <String, dynamic>{
      'html.changed': log.htmlChanged,
      'html.hash': log.htmlHash,
      'html.capturedAt': Timestamp.fromDate(log.capturedAt),
      'htmlSyncedAt': FieldValue.serverTimestamp(),
    };

    if (log.htmlCaptureId != null) {
      updates['html.htmlCaptureId'] = log.htmlCaptureId;
    }

    await _firestore
        .collection('participants')
        .doc(log.participantId)
        .collection('events')
        .doc(log.eventId)
        .update(updates);

    print('[UploadService] Updated event with HTML status: ${log.eventId} (changed: ${log.htmlChanged})');
  }

  /// Sync all data (events + OCR results + HTML) efficiently
  /// Returns a map with counts of synced items
  /// Sync EMA check-in responses to Firebase
  Future<int> syncEmaResponses({int batchSize = 50}) async {
    if (_isSyncingEma) {
      print('[UploadService] EMA sync already in progress, skipping');
      return 0;
    }

    _isSyncingEma = true;
    int totalSynced = 0;

    try {
      final unsyncedResponses = await database.getUnsyncedEmaResponses(limit: batchSize);
      if (unsyncedResponses.isEmpty) {
        return 0;
      }

      print('[UploadService] Processing batch of ${unsyncedResponses.length} EMA responses');

      final syncedIds = <String>[];
      for (final response in unsyncedResponses) {
        try {
          await _uploadEmaResponse(response);
          syncedIds.add(response.id);
        } catch (e) {
          print('[UploadService] Failed to sync EMA response ${response.id}: $e');
        }
      }

      if (syncedIds.isNotEmpty) {
        await database.markEmaResponsesAsSynced(syncedIds);
        totalSynced = syncedIds.length;
        print('[UploadService] EMA sync complete. Total: $totalSynced');
      }
    } finally {
      _isSyncingEma = false;
    }

    return totalSynced;
  }

  Future<void> _uploadEmaResponse(EmaResponse response) async {
    final docRef = _firestore
        .collection('participants')
        .doc(response.participantId)
        .collection('ema_responses')
        .doc(response.id);

    final data = <String, dynamic>{
      'id': response.id,
      'participantId': response.participantId,
      'sessionId': response.sessionId,
      'responses': response.responses, // Already JSON string
      'startedAt': Timestamp.fromDate(response.startedAt),
      'completedAt': Timestamp.fromDate(response.completedAt),
      'selfInitiated': response.selfInitiated,
      'syncedAt': FieldValue.serverTimestamp(),
    };

    await docRef.set(data);
    print('[UploadService] Uploaded EMA response: ${response.id}');
  }

  Future<Map<String, int>> syncAll({int eventBatchSize = 50, int ocrBatchSize = 50}) async {
    // Reset screenshot counter
    _screenshotsUploaded = 0;

    // Sync events first (includes OCR data for screenshots)
    final eventsSynced = await syncEvents(batchSize: eventBatchSize);

    // Sync any remaining OCR results (for events that were synced before OCR was done)
    final ocrSynced = await syncOcrResults(batchSize: ocrBatchSize);

    // Sync HTML captures (upload files + update events)
    final htmlCapturesSynced = await syncHtmlCaptures(batchSize: eventBatchSize);

    // Sync HTML status logs (update events with unchanged status)
    final htmlStatusLogsSynced = await syncHtmlStatusLogs(batchSize: eventBatchSize);

    // Sync EMA check-in responses
    final emaSynced = await syncEmaResponses(batchSize: eventBatchSize);

    return {
      'events': eventsSynced,
      'ocrResults': ocrSynced,
      'screenshots': _screenshotsUploaded,
      'htmlCaptures': htmlCapturesSynced,
      'htmlStatusLogs': htmlStatusLogsSynced,
      'emaResponses': emaSynced,
    };
  }

  /// Get sync status
  Future<Map<String, int>> getSyncStatus() async {
    final total = await database.getEventCount();
    final unsynced = await database.getUnsyncedEvents();
    final totalOcr = await database.getOcrResultCount();
    final unsyncedOcr = await database.getUnsyncedOcrResults();
    final pendingHtml = await database.getPendingHtmlSyncCount();
    final unsyncedEma = await database.getUnsyncedEmaResponses();

    return {
      'totalEvents': total,
      'syncedEvents': total - unsynced.length,
      'pendingEvents': unsynced.length,
      'totalOcr': totalOcr,
      'pendingOcr': unsyncedOcr.length,
      'pendingHtml': pendingHtml,
      'pendingEma': unsyncedEma.length,
    };
  }

  /// Check if currently syncing
  bool get isSyncing => _isSyncing;

  /// Register a new participant in Firebase
  Future<void> registerParticipant({
    required String participantId,
    required String visitorId,
    required DateTime enrolledAt,
  }) async {
    try {
      await _firestore.collection('participants').doc(participantId).set({
        'participantId': participantId,
        'visitorId': visitorId,
        'enrolledAt': Timestamp.fromDate(enrolledAt),
        'registeredAt': FieldValue.serverTimestamp(),
        'redditLoggedIn': false,
        'twitterLoggedIn': false,
      }, SetOptions(merge: true));

      print('[UploadService] Registered participant: $participantId');
    } catch (e) {
      print('[UploadService] Failed to register participant: $e');
      rethrow;
    }
  }
}
