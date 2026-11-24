import 'dart:async';

import 'package:cloud_firestore/cloud_firestore.dart' show Timestamp;
import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:smerb_app/features/storage/database/database.dart';
import 'package:smerb_app/features/sync/services/upload_service.dart';

/// The 2026-11-24 fix: HTML-stage merge writes must be rules-valid creates
/// when the screenshot event document does not exist yet (686175383: 22 pages
/// rejected with permission-denied and re-uploaded every cycle for four days).
void main() {
  group('UploadService.eventSkeleton', () {
    final ts = DateTime(2026, 11, 20, 15, 30, 12);
    final created = DateTime(2026, 11, 20, 15, 30, 12, 5);

    test('copies the local event row verbatim (merge onto an existing doc is a no-op)', () {
      final row = Event(
        id: 'e1', sessionId: 's1', participantId: 'p1', eventType: 'screenshot',
        timestamp: ts, platform: 'twitter', url: 'https://x.com/home',
        data: '{}', synced: false, syncRetryCount: 0, createdAt: created,
      );
      final m = UploadService.eventSkeleton(row,
          eventId: 'ignored', sessionId: 'ignored', participantId: 'ignored',
          platform: 'reddit', url: 'other', fallbackTimestamp: DateTime(2000));
      expect(m['id'], 'e1');
      expect(m['sessionId'], 's1');
      expect(m['participantId'], 'p1');
      expect(m['eventType'], 'screenshot');
      expect(m['timestamp'], Timestamp.fromDate(ts));
      expect(m['createdAt'], Timestamp.fromDate(created));
      expect(m['platform'], 'twitter');
      expect(m['url'], 'https://x.com/home');
    });

    test('falls back to the capture fields when the local row is gone', () {
      final m = UploadService.eventSkeleton(null,
          eventId: 'e2', sessionId: 's2', participantId: 'p2',
          platform: 'reddit', url: null, fallbackTimestamp: ts);
      // Exactly what firestore.rules isValidEvent() requires for a create.
      expect(m.keys, containsAll(['id', 'sessionId', 'participantId', 'eventType', 'timestamp']));
      expect(m['eventType'], 'screenshot');
      expect(m['timestamp'], Timestamp.fromDate(ts));
      expect(m['platform'], 'reddit');
      expect(m.containsKey('url'), isFalse);
      expect(m.containsKey('createdAt'), isFalse);
    });
  });

  group('UploadService.classifyHtmlError', () {
    test('names the failure kinds the dashboard shows', () {
      expect(UploadService.classifyHtmlError(Exception(
          '[cloud_firestore/permission-denied] The caller does not have permission')),
          'permission_denied');
      expect(UploadService.classifyHtmlError(Exception('HTML file not found: /x/y.gz')), 'file_missing');
      expect(UploadService.classifyHtmlError(TimeoutException('html event set')), 'timeout');
      expect(UploadService.classifyHtmlError(Exception('HTML upload timed out after 30s')), 'timeout');
      expect(UploadService.classifyHtmlError(Exception('[firebase_storage/unauthorized] nope')), 'storage');
      expect(UploadService.classifyHtmlError(Exception('SocketException: Failed host lookup')), 'network');
      expect(UploadService.classifyHtmlError(Exception('[cloud_firestore/unknown] weird')), 'firestore');
      expect(UploadService.classifyHtmlError(StateError('boom')), 'other');
    });
  });

  group('AppDatabase HTML diagnostics helpers', () {
    late AppDatabase db;
    setUp(() => db = AppDatabase.forTesting(NativeDatabase.memory()));
    tearDown(() => db.close());

    test('getEventsByIds returns only the rows that exist', () async {
      for (final id in ['a', 'b']) {
        await db.insertEvent(EventsCompanion(
          id: Value(id), sessionId: const Value('s'), participantId: const Value('p'),
          eventType: const Value('screenshot'), timestamp: Value(DateTime(2026, 11, 20)),
          platform: const Value('reddit'), data: const Value('{}'),
        ));
      }
      final rows = await db.getEventsByIds(['a', 'b', 'missing']);
      expect(rows.keys.toSet(), {'a', 'b'});
      expect(rows['a']!.eventType, 'screenshot');
      expect(await db.getEventsByIds([]), isEmpty);
    });

    test('getOldestUnsyncedHtmlCaptureAt ignores synced rows', () async {
      expect(await db.getOldestUnsyncedHtmlCaptureAt(), isNull);
      Future<void> add(String id, DateTime at, {bool synced = false}) =>
          db.into(db.htmlCaptures).insert(HtmlCapturesCompanion(
            id: Value(id), eventId: Value('e$id'), participantId: const Value('p'),
            sessionId: const Value('s'), htmlHash: const Value('h'),
            filePath: Value('/x/html/s/$id.html.gz'), platform: const Value('reddit'),
            capturedAt: Value(at), synced: Value(synced),
          ));
      await add('old-synced', DateTime(2026, 11, 1), synced: true);
      await add('mid', DateTime(2026, 11, 20, 10));
      await add('new', DateTime(2026, 11, 23));
      expect(await db.getOldestUnsyncedHtmlCaptureAt(), DateTime(2026, 11, 20, 10));
      expect(await db.getUnsyncedHtmlCaptureCount(), 2);
    });
  });
}
