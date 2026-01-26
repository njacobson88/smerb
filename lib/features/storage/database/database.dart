import 'dart:io';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as path;

part 'database.g.dart';

// ============================================================================
// TABLES
// ============================================================================

/// Events table - stores all captured events
class Events extends Table {
  TextColumn get id => text()();
  TextColumn get sessionId => text()();
  TextColumn get participantId => text()();
  TextColumn get eventType => text()();
  DateTimeColumn get timestamp => dateTime()();
  TextColumn get platform => text()();
  TextColumn get url => text().nullable()();
  TextColumn get data => text()(); // JSON string
  BoolColumn get synced => boolean().withDefault(const Constant(false))();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();

  @override
  Set<Column> get primaryKey => {id};
}

/// Sessions table - tracks browsing sessions
class Sessions extends Table {
  TextColumn get id => text()();
  TextColumn get participantId => text()();
  DateTimeColumn get startedAt => dateTime()();
  DateTimeColumn get endedAt => dateTime().nullable()();
  IntColumn get eventCount => integer().withDefault(const Constant(0))();
  TextColumn get deviceInfo => text().nullable()(); // JSON string

  @override
  Set<Column> get primaryKey => {id};
}

/// HTML Captures table - stores full page HTML when it changes
class HtmlCaptures extends Table {
  TextColumn get id => text()();
  TextColumn get eventId => text()(); // Links to screenshot event
  TextColumn get participantId => text()();
  TextColumn get sessionId => text()();
  TextColumn get htmlHash => text()(); // SHA-256 hash for change detection
  TextColumn get filePath => text()(); // Path to saved .html file
  IntColumn get charCount => integer().withDefault(const Constant(0))();
  TextColumn get url => text().nullable()();
  TextColumn get platform => text()();
  DateTimeColumn get capturedAt => dateTime()();
  BoolColumn get synced => boolean().withDefault(const Constant(false))();

  @override
  Set<Column> get primaryKey => {id};
}

/// HTML Status Log table - logs whether HTML changed for each capture
class HtmlStatusLogs extends Table {
  TextColumn get id => text()();
  TextColumn get eventId => text()(); // Links to screenshot event
  TextColumn get participantId => text()();
  TextColumn get sessionId => text()();
  BoolColumn get htmlChanged => boolean()(); // true if new HTML was stored
  TextColumn get htmlCaptureId => text().nullable()(); // References HtmlCapture
  TextColumn get htmlHash => text()(); // Hash at this point in time
  DateTimeColumn get capturedAt => dateTime()();
  BoolColumn get synced => boolean().withDefault(const Constant(false))();

  @override
  Set<Column> get primaryKey => {id};
}

/// EMA Responses table - stores check-in survey responses
class EmaResponses extends Table {
  TextColumn get id => text()();
  TextColumn get participantId => text()();
  TextColumn get sessionId => text()();
  TextColumn get responses => text()(); // JSON string of all question responses
  DateTimeColumn get startedAt => dateTime()();
  DateTimeColumn get completedAt => dateTime()();
  BoolColumn get selfInitiated => boolean().withDefault(const Constant(true))();
  BoolColumn get synced => boolean().withDefault(const Constant(false))();

  @override
  Set<Column> get primaryKey => {id};
}

/// OCR Results table - stores extracted text from screenshots
class OcrResults extends Table {
  TextColumn get id => text()();
  TextColumn get eventId => text()(); // Links to screenshot event
  TextColumn get participantId => text()();
  TextColumn get sessionId => text()();
  TextColumn get extractedText => text()();
  IntColumn get wordCount => integer().withDefault(const Constant(0))();
  IntColumn get processingTimeMs => integer().nullable()();
  DateTimeColumn get capturedAt => dateTime()(); // Original screenshot timestamp
  DateTimeColumn get processedAt => dateTime().withDefault(currentDateAndTime)();
  BoolColumn get synced => boolean().withDefault(const Constant(false))();

  @override
  Set<Column> get primaryKey => {id};
}

// ============================================================================
// DATABASE
// ============================================================================

@DriftDatabase(tables: [Events, Sessions, OcrResults, HtmlCaptures, HtmlStatusLogs, EmaResponses])
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(_openConnection());

  @override
  int get schemaVersion => 4;

  @override
  MigrationStrategy get migration => MigrationStrategy(
    onCreate: (Migrator m) => m.createAll(),
    onUpgrade: (Migrator m, int from, int to) async {
      if (from < 2) {
        await m.createTable(ocrResults);
      }
      if (from < 3) {
        await m.createTable(htmlCaptures);
        await m.createTable(htmlStatusLogs);
      }
      if (from < 4) {
        await m.createTable(emaResponses);
      }
    },
  );

  // ==========================================================================
  // EVENT QUERIES
  // ==========================================================================

  /// Insert a new event
  Future<int> insertEvent(EventsCompanion event) {
    return into(events).insert(event);
  }

  /// Get all events
  Future<List<Event>> getAllEvents() {
    return select(events).get();
  }

  /// Get events by type
  Future<List<Event>> getEventsByType(String type) {
    return (select(events)..where((e) => e.eventType.equals(type))).get();
  }

  /// Get unsynced events
  Future<List<Event>> getUnsyncedEvents({int? limit}) {
    final query = select(events)..where((e) => e.synced.equals(false));
    if (limit != null) {
      query.limit(limit);
    }
    return query.get();
  }

  /// Mark events as synced
  Future<int> markEventsAsSynced(List<String> eventIds) {
    return (update(events)..where((e) => e.id.isIn(eventIds)))
        .write(const EventsCompanion(synced: Value(true)));
  }

  /// Get event count
  Future<int> getEventCount() async {
    final count = countAll();
    final query = selectOnly(events)..addColumns([count]);
    final result = await query.getSingle();
    return result.read(count) ?? 0;
  }

  /// Get event count by type
  Future<Map<String, int>> getEventCountByType() async {
    final query = selectOnly(events)
      ..addColumns([events.eventType, countAll()])
      ..groupBy([events.eventType]);

    final results = await query.get();
    return {
      for (var row in results)
        row.read(events.eventType)!: row.read(countAll()) ?? 0,
    };
  }

  /// Delete all events
  Future<int> deleteAllEvents() {
    return delete(events).go();
  }

  // ==========================================================================
  // SESSION QUERIES
  // ==========================================================================

  /// Insert a new session
  Future<int> insertSession(SessionsCompanion session) {
    return into(sessions).insert(session);
  }

  /// Get current session (not ended)
  Future<Session?> getCurrentSession(String participantId) {
    return (select(sessions)
          ..where((s) =>
              s.participantId.equals(participantId) & s.endedAt.isNull())
          ..limit(1))
        .getSingleOrNull();
  }

  /// End a session
  Future<int> endSession(String sessionId, DateTime endTime) {
    return (update(sessions)..where((s) => s.id.equals(sessionId)))
        .write(SessionsCompanion(endedAt: Value(endTime)));
  }

  /// Increment session event count
  Future<void> incrementSessionEventCount(String sessionId) async {
    final session = await (select(sessions)
          ..where((s) => s.id.equals(sessionId)))
        .getSingle();

    await (update(sessions)..where((s) => s.id.equals(sessionId))).write(
      SessionsCompanion(
        eventCount: Value(session.eventCount + 1),
      ),
    );
  }

  // ==========================================================================
  // OCR RESULTS QUERIES
  // ==========================================================================

  /// Insert a new OCR result
  Future<int> insertOcrResult(OcrResultsCompanion result) {
    return into(ocrResults).insert(result);
  }

  /// Get OCR result for an event
  Future<OcrResult?> getOcrResultForEvent(String eventId) {
    return (select(ocrResults)..where((o) => o.eventId.equals(eventId)))
        .getSingleOrNull();
  }

  /// Get unsynced OCR results
  Future<List<OcrResult>> getUnsyncedOcrResults({int? limit}) {
    final query = select(ocrResults)..where((o) => o.synced.equals(false));
    if (limit != null) {
      query.limit(limit);
    }
    return query.get();
  }

  /// Mark OCR results as synced
  Future<int> markOcrResultsAsSynced(List<String> resultIds) {
    return (update(ocrResults)..where((o) => o.id.isIn(resultIds)))
        .write(const OcrResultsCompanion(synced: Value(true)));
  }

  /// Get OCR result count
  Future<int> getOcrResultCount() async {
    final count = countAll();
    final query = selectOnly(ocrResults)..addColumns([count]);
    final result = await query.getSingle();
    return result.read(count) ?? 0;
  }

  /// Get pending OCR count (screenshot events without OCR results)
  Future<int> getPendingOcrCount() async {
    // Get all screenshot event IDs
    final screenshotEvents = await (select(events)
          ..where((e) => e.eventType.equals('screenshot')))
        .get();

    if (screenshotEvents.isEmpty) return 0;

    // Get OCR results for those events
    final eventIds = screenshotEvents.map((e) => e.id).toList();
    final ocrResultsList = await (select(ocrResults)
          ..where((o) => o.eventId.isIn(eventIds)))
        .get();

    final processedIds = ocrResultsList.map((o) => o.eventId).toSet();
    return eventIds.where((id) => !processedIds.contains(id)).length;
  }

  // ==========================================================================
  // HTML CAPTURE QUERIES
  // ==========================================================================

  /// Insert a new HTML capture
  Future<int> insertHtmlCapture(HtmlCapturesCompanion capture) {
    return into(htmlCaptures).insert(capture);
  }

  /// Get unsynced HTML captures
  Future<List<HtmlCapture>> getUnsyncedHtmlCaptures({int? limit}) {
    final query = select(htmlCaptures)..where((h) => h.synced.equals(false));
    if (limit != null) {
      query.limit(limit);
    }
    return query.get();
  }

  /// Mark HTML captures as synced
  Future<int> markHtmlCapturesAsSynced(List<String> captureIds) {
    return (update(htmlCaptures)..where((h) => h.id.isIn(captureIds)))
        .write(const HtmlCapturesCompanion(synced: Value(true)));
  }

  // ==========================================================================
  // HTML STATUS LOG QUERIES
  // ==========================================================================

  /// Insert a new HTML status log entry
  Future<int> insertHtmlStatusLog(HtmlStatusLogsCompanion log) {
    return into(htmlStatusLogs).insert(log);
  }

  /// Get unsynced HTML status logs
  Future<List<HtmlStatusLog>> getUnsyncedHtmlStatusLogs({int? limit}) {
    final query = select(htmlStatusLogs)..where((h) => h.synced.equals(false));
    if (limit != null) {
      query.limit(limit);
    }
    return query.get();
  }

  /// Mark HTML status logs as synced
  Future<int> markHtmlStatusLogsSynced(List<String> logIds) {
    return (update(htmlStatusLogs)..where((h) => h.id.isIn(logIds)))
        .write(const HtmlStatusLogsCompanion(synced: Value(true)));
  }

  /// Get pending HTML status log count
  Future<int> getPendingHtmlSyncCount() async {
    final unsyncedCaptures = await getUnsyncedHtmlCaptures();
    final unsyncedLogs = await getUnsyncedHtmlStatusLogs();
    return unsyncedCaptures.length + unsyncedLogs.length;
  }

  // ==========================================================================
  // EMA RESPONSE QUERIES
  // ==========================================================================

  /// Insert a new EMA response
  Future<int> insertEmaResponse(EmaResponsesCompanion response) {
    return into(emaResponses).insert(response);
  }

  /// Get unsynced EMA responses
  Future<List<EmaResponse>> getUnsyncedEmaResponses({int? limit}) {
    final query = select(emaResponses)..where((e) => e.synced.equals(false));
    if (limit != null) {
      query.limit(limit);
    }
    return query.get();
  }

  /// Mark EMA responses as synced
  Future<int> markEmaResponsesAsSynced(List<String> responseIds) {
    return (update(emaResponses)..where((e) => e.id.isIn(responseIds)))
        .write(const EmaResponsesCompanion(synced: Value(true)));
  }

  /// Get screenshot events pending OCR processing
  Future<List<Event>> getScreenshotsPendingOcr({int? limit}) async {
    // Get all screenshot events
    final screenshotEvents = await (select(events)
          ..where((e) => e.eventType.equals('screenshot')))
        .get();

    if (screenshotEvents.isEmpty) return [];

    // Get already processed event IDs
    final eventIds = screenshotEvents.map((e) => e.id).toList();
    final ocrResultsList = await (select(ocrResults)
          ..where((o) => o.eventId.isIn(eventIds)))
        .get();

    final processedIds = ocrResultsList.map((o) => o.eventId).toSet();

    // Filter to unprocessed
    final pending = screenshotEvents
        .where((e) => !processedIds.contains(e.id))
        .toList();

    if (limit != null && pending.length > limit) {
      return pending.sublist(0, limit);
    }
    return pending;
  }
}

// ============================================================================
// DATABASE CONNECTION
// ============================================================================

LazyDatabase _openConnection() {
  return LazyDatabase(() async {
    final dbFolder = await getApplicationDocumentsDirectory();
    final file = File(path.join(dbFolder.path, 'smerb.db'));
    return NativeDatabase(file);
  });
}
