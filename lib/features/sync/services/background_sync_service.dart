import 'dart:async';
import 'dart:isolate';
import 'package:flutter/foundation.dart';
import '../../storage/database/database.dart';
import '../../ocr/services/ocr_service.dart';
import 'upload_service.dart';

/// Background sync service that automatically syncs data every 30 seconds.
/// Runs operations asynchronously to avoid blocking the UI.
class BackgroundSyncService {
  final AppDatabase database;
  final UploadService uploadService;
  final OcrService ocrService;

  Timer? _syncTimer;
  bool _isSyncing = false;
  bool _isProcessingOcr = false;
  bool _isRunning = false;

  // Sync interval
  static const Duration syncInterval = Duration(seconds: 30);

  // Callbacks for status updates
  void Function(SyncStatus)? onSyncStatusChanged;

  // Last sync results
  SyncStatus _lastStatus = SyncStatus.idle();

  BackgroundSyncService({
    required this.database,
    required this.uploadService,
    required this.ocrService,
  });

  /// Get current sync status
  SyncStatus get lastStatus => _lastStatus;

  /// Check if sync is currently running
  bool get isSyncing => _isSyncing;

  /// Check if OCR is currently processing
  bool get isProcessingOcr => _isProcessingOcr;

  /// Check if background service is running
  bool get isRunning => _isRunning;

  /// Start the background sync service
  void start() {
    if (_isRunning) {
      print('[BackgroundSync] Already running');
      return;
    }

    _isRunning = true;
    print('[BackgroundSync] Starting with ${syncInterval.inSeconds}s interval');

    // Run initial sync after a short delay
    Future.delayed(const Duration(seconds: 5), () {
      if (_isRunning) _runSyncCycle();
    });

    // Schedule periodic sync
    _syncTimer = Timer.periodic(syncInterval, (_) {
      _runSyncCycle();
    });
  }

  /// Stop the background sync service
  void stop() {
    print('[BackgroundSync] Stopping');
    _syncTimer?.cancel();
    _syncTimer = null;
    _isRunning = false;
  }

  /// Run a single sync cycle (OCR + upload)
  Future<void> _runSyncCycle() async {
    if (_isSyncing) {
      print('[BackgroundSync] Sync already in progress, skipping');
      return;
    }

    _isSyncing = true;
    _updateStatus(SyncStatus.syncing());

    try {
      // Step 1: Process any pending OCR (runs async, non-blocking)
      await _processOcrInBackground();

      // Step 2: Sync to Firebase (runs async, non-blocking)
      await _syncToFirebase();

      // Update status
      final syncStatus = await uploadService.getSyncStatus();
      final ocrStatus = await ocrService.getOcrStatus();

      _updateStatus(SyncStatus.completed(
        eventsSynced: syncStatus['syncedEvents'] ?? 0,
        pendingEvents: syncStatus['pendingEvents'] ?? 0,
        pendingOcr: ocrStatus['pending'] ?? 0,
        pendingHtml: syncStatus['pendingHtml'] ?? 0,
        pendingEma: syncStatus['pendingEma'] ?? 0,
      ));

    } catch (e) {
      print('[BackgroundSync] Sync cycle error: $e');
      _updateStatus(SyncStatus.error(e.toString()));
    } finally {
      _isSyncing = false;
    }
  }

  /// Process OCR in background (non-blocking)
  Future<void> _processOcrInBackground() async {
    if (_isProcessingOcr) return;

    _isProcessingOcr = true;

    try {
      // Check if there's pending OCR work
      final pendingCount = await database.getPendingOcrCount();

      if (pendingCount > 0) {
        print('[BackgroundSync] Processing $pendingCount pending OCR items');

        // Process in small batches to avoid blocking the main isolate.
        final processed = await ocrService.processPendingScreenshots(batchSize: 5);

        print('[BackgroundSync] Processed $processed OCR items');
      }
    } catch (e) {
      print('[BackgroundSync] OCR processing error: $e');
    } finally {
      _isProcessingOcr = false;
    }
  }

  /// Sync data to Firebase (non-blocking)
  Future<void> _syncToFirebase() async {
    try {
      // Get pending counts first
      final unsyncedEvents = await database.getUnsyncedEvents(limit: 1);
      final unsyncedOcr = await database.getUnsyncedOcrResults(limit: 1);
      final pendingHtml = await database.getPendingHtmlSyncCount();
      final unsyncedEma = await database.getUnsyncedEmaResponses(limit: 1);

      if (unsyncedEvents.isEmpty && unsyncedOcr.isEmpty && pendingHtml == 0 && unsyncedEma.isEmpty) {
        print('[BackgroundSync] Nothing to sync');
        return;
      }

      print('[BackgroundSync] Syncing to Firebase...');

      // Sync events, OCR results, HTML captures/logs, and EMA responses
      // Using smaller batch sizes for smoother background operation
      final results = await uploadService.syncAll(
        eventBatchSize: 25,
        ocrBatchSize: 25,
      );

      print('[BackgroundSync] Synced ${results['events']} events, '
          '${results['ocrResults']} OCR, '
          '${results['htmlCaptures']} HTML captures, '
          '${results['htmlStatusLogs']} HTML status logs, '
          '${results['emaResponses']} EMA responses');

    } catch (e) {
      print('[BackgroundSync] Firebase sync error: $e');
      rethrow;
    }
  }

  /// Force an immediate sync (can be called from UI)
  Future<void> syncNow() async {
    print('[BackgroundSync] Manual sync triggered');
    await _runSyncCycle();
  }

  /// Update status and notify listeners
  void _updateStatus(SyncStatus status) {
    _lastStatus = status;
    onSyncStatusChanged?.call(status);
  }

  /// Dispose the service
  void dispose() {
    stop();
  }
}

/// Represents the current sync status
class SyncStatus {
  final SyncState state;
  final int eventsSynced;
  final int pendingEvents;
  final int pendingOcr;
  final int pendingHtml;
  final int pendingEma;
  final String? errorMessage;
  final DateTime timestamp;

  SyncStatus._({
    required this.state,
    this.eventsSynced = 0,
    this.pendingEvents = 0,
    this.pendingOcr = 0,
    this.pendingHtml = 0,
    this.pendingEma = 0,
    this.errorMessage,
    DateTime? timestamp,
  }) : timestamp = timestamp ?? DateTime.now();

  factory SyncStatus.idle() => SyncStatus._(state: SyncState.idle);

  factory SyncStatus.syncing() => SyncStatus._(state: SyncState.syncing);

  factory SyncStatus.completed({
    int eventsSynced = 0,
    int pendingEvents = 0,
    int pendingOcr = 0,
    int pendingHtml = 0,
    int pendingEma = 0,
  }) =>
      SyncStatus._(
        state: SyncState.completed,
        eventsSynced: eventsSynced,
        pendingEvents: pendingEvents,
        pendingOcr: pendingOcr,
        pendingHtml: pendingHtml,
        pendingEma: pendingEma,
      );

  factory SyncStatus.error(String message) => SyncStatus._(
        state: SyncState.error,
        errorMessage: message,
      );

  bool get isIdle => state == SyncState.idle;
  bool get isSyncing => state == SyncState.syncing;
  bool get isCompleted => state == SyncState.completed;
  bool get hasError => state == SyncState.error;
  bool get hasPending => pendingEvents > 0 || pendingOcr > 0 || pendingHtml > 0 || pendingEma > 0;
}

enum SyncState {
  idle,
  syncing,
  completed,
  error,
}
