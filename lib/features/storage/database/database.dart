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

// ============================================================================
// DATABASE
// ============================================================================

@DriftDatabase(tables: [Events, Sessions])
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(_openConnection());

  @override
  int get schemaVersion => 1;

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

  /// Get events for a session
  Future<List<Event>> getEventsForSession(String sessionId) {
    return (select(events)..where((e) => e.sessionId.equals(sessionId))).get();
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

  /// Delete events older than a date
  Future<int> deleteEventsOlderThan(DateTime date) {
    return (delete(events)..where((e) => e.createdAt.isSmallerThanValue(date)))
        .go();
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

  /// Get all sessions
  Future<List<Session>> getAllSessions() {
    return select(sessions).get();
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
