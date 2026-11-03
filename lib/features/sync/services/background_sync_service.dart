import 'dart:async';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'dart:io';
import 'package:path_provider/path_provider.dart';
import '../../storage/database/database.dart';
import '../../storage/services/local_media_retention.dart';
import '../../capture/services/screenshot_service.dart';
import 'package:drift/drift.dart' show Value;
import 'package:uuid/uuid.dart';
import 'dart:convert';
import '../../ocr/services/ocr_service.dart';
import '../../settings/services/pause_service.dart';
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
  bool _userPaused = false;
  int _syncCycleCount = 0;
  bool _sweptSinceLaunch = false;
  bool _lastCycleTruncated = false;
  Timer? _followUpTimer;

  // Sync interval
  static const Duration syncInterval = Duration(seconds: 30);

  // Run data retention every ~120 cycles (~1 hour)
  static const int _retentionInterval = 120;
  // Check cache pressure every ~10 cycles (~5 min): a directory walk of a few
  // thousand files, cheap enough at that cadence, and capture re-checks the
  // cap on every tick while paused so it resumes within seconds of relief.
  static const int _pressureInterval = 10;
  int _cyclesSincePressureCheck = 0;

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

  /// Temporarily pause sync (e.g., 5-min privacy mode).
  bool get isUserPaused => _userPaused;
  void setUserPaused(bool paused) {
    _userPaused = paused;
    print('[BackgroundSync] User pause: $paused');
  }

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
    _followUpTimer?.cancel();
    _followUpTimer = null;
    _isRunning = false;
  }

  /// Check if the device has network connectivity
  Future<bool> _hasNetworkConnectivity() async {
    try {
      final results = await Connectivity().checkConnectivity();
      final connected = results.any((r) =>
          r == ConnectivityResult.wifi ||
          r == ConnectivityResult.mobile ||
          r == ConnectivityResult.ethernet);
      return connected;
    } catch (e) {
      // If we can't check, assume connected and let uploads fail naturally
      return true;
    }
  }

  /// Run a single sync cycle (OCR + upload)
  Future<void> _runSyncCycle() async {
    if (_isSyncing) {
      print('[BackgroundSync] Sync already in progress, skipping');
      return;
    }
    if (_userPaused || PauseService().isPaused) {
      return;
    }

    _isSyncing = true;
    _updateStatus(SyncStatus.syncing());

    try {
      // Step 0: Check network connectivity before attempting uploads
      final hasNetwork = await _hasNetworkConnectivity();

      // Step 0b: First cycle after launch — free local media we no longer
      // need BEFORE anything slow runs, so a device stuck at the cache cap
      // recovers within seconds of opening the app.
      if (!_sweptSinceLaunch) {
        _sweptSinceLaunch = true;
        await _sweepLocalMedia();
        await _relieveCachePressure();
      }

      // Step 1: Process any pending OCR (bounded; local-only, no network)
      await _processOcrInBackground();

      // Step 2: Sync to Firebase (only if online)
      if (!hasNetwork) {
        print('[BackgroundSync] No network connectivity, skipping Firebase sync');
      } else {
        await _syncToFirebase();
      }

      // Step 3: Periodically prune old synced data (~hourly), then free the
      // local media files nothing needs any more (same cadence: a few
      // thousand stat() calls). Also runs once at launch, see Step 0b.
      if (++_cyclesSincePressureCheck >= _pressureInterval) {
        _cyclesSincePressureCheck = 0;
        await _relieveCachePressure();
      }

      _syncCycleCount++;
      if (_syncCycleCount >= _retentionInterval) {
        _syncCycleCount = 0;
        final pruned = await database.pruneOldSyncedData(retentionDays: 7);
        if (pruned > 0) {
          print('[BackgroundSync] Pruned $pruned old synced rows');
        }
        await _sweepLocalMedia();
      }

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
      // A budgeted cycle that left work behind continues almost immediately
      // (OCR gets its turn at the top of the next cycle), instead of letting
      // a backlog wait for the 30 s timer.
      if (_lastCycleTruncated && _isRunning) {
        _lastCycleTruncated = false;
        _followUpTimer?.cancel();
        _followUpTimer = Timer(const Duration(seconds: 2), _runSyncCycle);
      }
    }
  }

  /// Delete screenshot files that are uploaded and either OCR'd or past the
  /// OCR grace period, plus orphans no event row references (rows pruned at
  /// 30 days used to leave their files behind forever — see
  /// LocalMediaRetention). Never touches a file whose event is not uploaded.
  Future<void> _sweepLocalMedia() async {
    try {
      final docs = await getApplicationDocumentsDirectory();
      final dir = Directory('${docs.path}/screenshots');
      if (!await dir.exists()) return;

      final now = DateTime.now();
      final onDisk = <String, double>{};
      await for (final entity in dir.list(recursive: true, followLinks: false)) {
        if (entity is! File) continue;
        DateTime modified;
        try {
          modified = await entity.lastModified();
        } catch (_) {
          continue;
        }
        onDisk[entity.path] = now.difference(modified).inMinutes / 1440.0;
      }
      if (onDisk.isEmpty) return;

      final referenced = await database.getReferencedScreenshotFiles();
      final doomed = LocalMediaRetention.filesToDelete(
          filesOnDisk: onDisk, referencedFiles: referenced);

      int deleted = 0, bytes = 0;
      for (final path in doomed) {
        try {
          final f = File(path);
          bytes += await f.length();
          await f.delete();
          deleted++;
        } catch (e) {
          print('[BackgroundSync] sweep could not delete $path: $e');
        }
      }
      if (deleted > 0) {
        print('[BackgroundSync] Swept $deleted local screenshot files '
            '(${(bytes / 1048576).toStringAsFixed(0)} MB); '
            '${onDisk.length - deleted} remain, ${onDisk.length - referenced.length} were orphans');
      }

      // HTML snapshots are deleted right after upload, so the only thing that
      // can accumulate is a file no html_captures row points at any more.
      final htmlDir = Directory('${docs.path}/html');
      if (await htmlDir.exists()) {
        final htmlRefs = await database.getReferencedHtmlFiles();
        int htmlDeleted = 0;
        await for (final entity in htmlDir.list(recursive: true, followLinks: false)) {
          if (entity is File && !htmlRefs.contains(entity.path)) {
            try { await entity.delete(); htmlDeleted++; } catch (_) {}
          }
        }
        if (htmlDeleted > 0) print('[BackgroundSync] Swept $htmlDeleted orphan HTML files');
      }
    } catch (e) {
      print('[BackgroundSync] local media sweep error: $e');
    }
  }

  /// Screenshots come first (PI decision 2026-11-03): when the app's own
  /// cache is about to hit the cap that pauses capture, drop the OLDEST
  /// unsent HTML page captures — only as much as needed to get back under
  /// the cap — and leave an `html_dropped_for_space` event saying exactly
  /// what was lost. Nothing else is ever deleted here; uploaded files are the
  /// sweep's job and unsent screenshots are never touched.
  Future<void> _relieveCachePressure() async {
    try {
      final usage = await ScreenshotService.getLocalStorageBytes();
      if (usage < 0) return;
      const cap = ScreenshotService.maxLocalStorageMb * 1024 * 1024;
      final need = CachePressureValve.bytesToFree(usageBytes: usage, capBytes: cap);
      if (need == 0) return;

      // Oldest unsent captures first; size each file as we go.
      final candidates = await database.getUnsyncedHtmlCaptures(limit: 5000);
      if (candidates.isEmpty) {
        print('[BackgroundSync] cache at ${usage ~/ 1048576} MB but no unsent HTML to drop');
        return;
      }
      final sized = <({String id, int bytes})>[];
      final byId = <String, HtmlCapture>{};
      for (final c in candidates) {
        int bytes = 0;
        try { bytes = await File(c.filePath).length(); } catch (_) {}
        sized.add((id: c.id, bytes: bytes));
        byId[c.id] = c;
      }
      final doomed = CachePressureValve.pickToDrop(oldestFirst: sized, bytesNeeded: need);
      if (doomed.isEmpty) return;

      int freed = 0, deleted = 0;
      final dropped = <HtmlCapture>[];
      for (final id in doomed) {
        final c = byId[id]!;
        try {
          final f = File(c.filePath);
          if (await f.exists()) { freed += await f.length(); await f.delete(); deleted++; }
          dropped.add(c);
        } catch (e) {
          print('[BackgroundSync] could not drop ${c.filePath}: $e');
        }
      }
      if (dropped.isEmpty) return;
      // Retire the rows so the upload queue never looks for these files.
      await database.markHtmlCapturesAsSynced(dropped.map((c) => c.id).toList());
      final times = dropped.map((c) => c.capturedAt).toList()..sort();
      final first = dropped.first;
      await database.insertEvent(EventsCompanion(
        id: Value(const Uuid().v4()),
        sessionId: Value(first.sessionId),
        participantId: Value(first.participantId),
        eventType: const Value('html_dropped_for_space'),
        timestamp: Value(DateTime.now()),
        platform: Value(first.platform),
        data: Value(jsonEncode({
          'count': dropped.length,
          'filesDeleted': deleted,
          'bytesFreed': freed,
          'usageMbBefore': usage ~/ 1048576,
          'capMb': ScreenshotService.maxLocalStorageMb,
          'oldestCapturedAt': times.first.toIso8601String(),
          'newestCapturedAt': times.last.toIso8601String(),
          'eventIds': dropped.take(50).map((c) => c.eventId).toList(),
        })),
      ));
      print('[BackgroundSync] Cache pressure: dropped ${dropped.length} oldest unsent HTML captures '
          '(${freed ~/ 1048576} MB) — cache was ${usage ~/ 1048576} MB of ${ScreenshotService.maxLocalStorageMb} MB');
    } catch (e) {
      print('[BackgroundSync] cache pressure check error: $e');
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
        // Bounded per cycle so upload + the media sweep still run every ~30s
        // even with a large backlog (the loop used to drain it all first).
        final processed = await ocrService.processPendingScreenshots(batchSize: 5, maxItems: 50);

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

      final bytesUploaded = results['bytesUploaded'] ?? 0;
      final bytesStr = bytesUploaded > 1024 * 1024
          ? '${(bytesUploaded / (1024 * 1024)).toStringAsFixed(1)}MB'
          : '${(bytesUploaded / 1024).toStringAsFixed(0)}KB';

      print('[BackgroundSync] Synced ${results['events']} events, '
          '${results['ocrResults']} OCR, '
          '${results['htmlCaptures']} HTML captures, '
          '${results['htmlStatusLogs']} HTML status logs, '
          '${results['emaResponses']} EMA responses '
          '($bytesStr uploaded)'
          '${results['truncated'] == 1 ? ' — budget hit, more pending' : ''}');
      // Follow up quickly only when the cycle both ran out of time AND got
      // something through; a stage that fails every item in milliseconds
      // (bad network, rejected writes) must wait for the regular timer rather
      // than spin every few seconds.
      final progressed = (results['events'] ?? 0) + (results['ocrResults'] ?? 0) +
          (results['htmlCaptures'] ?? 0) + (results['htmlStatusLogs'] ?? 0) +
          (results['emaResponses'] ?? 0) + (results['contentEvents'] ?? 0) > 0;
      _lastCycleTruncated = results['truncated'] == 1 && progressed;

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
