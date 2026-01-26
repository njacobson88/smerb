import 'dart:convert';
import 'package:drift/drift.dart' as drift;
import 'package:uuid/uuid.dart';
import '../../../features/storage/database/database.dart';

/// Service that handles event capture from JavaScript bridge
class CaptureService {
  final AppDatabase _database;
  final String participantId;
  String? _currentSessionId;

  // Public getter for current session ID
  String? get currentSessionId => _currentSessionId;

  CaptureService({
    required AppDatabase database,
    required this.participantId,
  }) : _database = database;

  // ==========================================================================
  // SESSION MANAGEMENT
  // ==========================================================================

  /// Start a new capture session
  Future<String> startSession({Map<String, dynamic>? deviceInfo}) async {
    // End any existing session
    if (_currentSessionId != null) {
      await endSession();
    }

    final sessionId = const Uuid().v4();
    final session = SessionsCompanion(
      id: drift.Value(sessionId),
      participantId: drift.Value(participantId),
      startedAt: drift.Value(DateTime.now()),  // Local time for participant
      deviceInfo:
          drift.Value(deviceInfo != null ? jsonEncode(deviceInfo) : null),
    );

    await _database.insertSession(session);
    _currentSessionId = sessionId;

    print('[CaptureService] Started session: $sessionId');
    return sessionId;
  }

  /// End the current session
  Future<void> endSession() async {
    if (_currentSessionId == null) return;

    await _database.endSession(_currentSessionId!, DateTime.now());  // Local time
    print('[CaptureService] Ended session: $_currentSessionId');
    _currentSessionId = null;
  }

  /// Get or create current session
  Future<String> _ensureSession() async {
    if (_currentSessionId != null) return _currentSessionId!;

    // Check if there's an existing open session
    final existingSession = await _database.getCurrentSession(participantId);
    if (existingSession != null) {
      _currentSessionId = existingSession.id;
      return _currentSessionId!;
    }

    // Create new session
    return await startSession();
  }

  // ==========================================================================
  // EVENT CAPTURE
  // ==========================================================================

  /// Process an event received from JavaScript
  Future<void> processJavaScriptEvent(String jsonPayload) async {
    try {
      final data = jsonDecode(jsonPayload) as Map<String, dynamic>;

      final eventType = data['type'] as String?;
      if (eventType == null) {
        print('[CaptureService] Missing event type in payload');
        return;
      }

      // Handle special events
      if (eventType == 'observer_ready') {
        print('[CaptureService] Observer ready: ${data['platform']}');
        return;
      }

      // Ensure we have a session
      final sessionId = await _ensureSession();

      // Create event
      final eventId = const Uuid().v4();
      final event = EventsCompanion(
        id: drift.Value(eventId),
        sessionId: drift.Value(sessionId),
        participantId: drift.Value(participantId),
        eventType: drift.Value(eventType),
        timestamp: drift.Value(
          DateTime.fromMillisecondsSinceEpoch(
            data['timestamp'] as int,
            isUtc: true,
          ),
        ),
        platform: drift.Value(data['platform'] as String? ?? 'unknown'),
        url: drift.Value(data['url'] as String?),
        data: drift.Value(jsonEncode(data['data'] ?? {})),
        synced: const drift.Value(false),
        createdAt: drift.Value(DateTime.now()),  // Local time for participant
      );

      // Save to database
      await _database.insertEvent(event);
      await _database.incrementSessionEventCount(sessionId);

      print('[CaptureService] Captured event: $eventType (${data['platform']})');
    } catch (e, stackTrace) {
      print('[CaptureService] Error processing event: $e');
      print(stackTrace);
    }
  }

  // ==========================================================================
  // STATISTICS
  // ==========================================================================

  /// Get total event count
  Future<int> getTotalEventCount() {
    return _database.getEventCount();
  }

  /// Get event counts by type
  Future<Map<String, int>> getEventCountsByType() {
    return _database.getEventCountByType();
  }

  /// Get all events (for debugging)
  Future<List<Event>> getAllEvents() {
    return _database.getAllEvents();
  }

  /// Clear all data (for testing)
  Future<void> clearAllData() async {
    await _database.deleteAllEvents();
    print('[CaptureService] Cleared all events');
  }
}
