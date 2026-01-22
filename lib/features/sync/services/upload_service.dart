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

  // Sync progress tracking
  int _eventsSynced = 0;
  int _ocrResultsSynced = 0;
  int _screenshotsUploaded = 0;

  UploadService({
    required this.database,
    FirebaseFirestore? firestore,
    FirebaseStorage? storage,
  })  : _firestore = firestore ?? FirebaseFirestore.instance,
        _storage = storage ?? FirebaseStorage.instance;

  /// Get sync progress
  Map<String, int> get syncProgress => {
    'eventsSynced': _eventsSynced,
    'ocrResultsSynced': _ocrResultsSynced,
    'screenshotsUploaded': _screenshotsUploaded,
  };

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

    _eventsSynced++;
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
          _ocrResultsSynced += syncedIds.length;
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

  /// Sync all data (events + OCR results) efficiently
  /// Returns a map with counts of synced items
  Future<Map<String, int>> syncAll({int eventBatchSize = 50, int ocrBatchSize = 50}) async {
    // Reset progress counters
    _eventsSynced = 0;
    _ocrResultsSynced = 0;
    _screenshotsUploaded = 0;

    // Sync events first (includes OCR data for screenshots)
    final eventsSynced = await syncEvents(batchSize: eventBatchSize);

    // Sync any remaining OCR results (for events that were synced before OCR was done)
    final ocrSynced = await syncOcrResults(batchSize: ocrBatchSize);

    return {
      'events': eventsSynced,
      'ocrResults': ocrSynced,
      'screenshots': _screenshotsUploaded,
    };
  }

  /// Get sync status
  Future<Map<String, int>> getSyncStatus() async {
    final total = await database.getEventCount();
    final unsynced = await database.getUnsyncedEvents();
    final totalOcr = await database.getOcrResultCount();
    final unsyncedOcr = await database.getUnsyncedOcrResults();

    return {
      'totalEvents': total,
      'syncedEvents': total - unsynced.length,
      'pendingEvents': unsynced.length,
      'totalOcr': totalOcr,
      'pendingOcr': unsyncedOcr.length,
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

  /// Update participant login status in Firebase
  Future<void> updateParticipantLogin({
    required String participantId,
    required String platform,
    required bool loggedIn,
    String? username,
  }) async {
    try {
      final updates = <String, dynamic>{
        '${platform}LoggedIn': loggedIn,
        '${platform}LoginAt': loggedIn ? FieldValue.serverTimestamp() : null,
      };
      if (username != null) {
        updates['${platform}Username'] = username;
      }

      await _firestore.collection('participants').doc(participantId).update(updates);

      print('[UploadService] Updated $platform login for $participantId: $loggedIn');
    } catch (e) {
      print('[UploadService] Failed to update participant login: $e');
      // Don't rethrow - login tracking failure shouldn't break the app
    }
  }
}
