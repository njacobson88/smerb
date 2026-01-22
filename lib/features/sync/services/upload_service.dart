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

    // Handle screenshot events specially - upload file to Storage
    String? storageUrl;
    if (event.eventType == 'screenshot') {
      storageUrl = await _uploadScreenshot(event, eventData);
    }

    // Prepare Firestore document
    final docData = {
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

  /// Get sync status
  Future<Map<String, int>> getSyncStatus() async {
    final total = await database.getEventCount();
    final unsynced = await database.getUnsyncedEvents();

    return {
      'total': total,
      'synced': total - unsynced.length,
      'pending': unsynced.length,
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
