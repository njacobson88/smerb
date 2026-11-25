import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:isolate';
import 'dart:math' as math;
import 'dart:ui' show DartPluginRegistrant, IsolateNameServer;

import 'package:drift/drift.dart' show Value;
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:uuid/uuid.dart';
import 'package:workmanager/workmanager.dart';

import '../../../firebase_options.dart';
import '../../onboarding/services/participant_service.dart';
import '../../storage/database/database.dart';
import 'background_sync_service.dart';
import 'upload_service.dart';

/// Uploads that continue while the app is not open (2026-11-24).
///
/// Until 1.0.28 every upload ran on a 30 s timer in the UI isolate, so a
/// participant who browsed for an hour on a slow connection and then put the
/// phone away left hundreds of pages waiting until the next time they opened
/// the app (322475615: ~9,850 pages pending for weeks, 2.9k dropped by the
/// cache valve). This file adds three OS-scheduled entry points, all through
/// the `workmanager` plugin so one code path serves both platforms:
///
/// * [kPeriodicSyncTask] — Android WorkManager periodic job (every ~15 min,
///   Wi-Fi, battery not low, up to 8 min of uploads); on iOS the same name is
///   a BGAppRefreshTask (~20 s, whenever iOS decides).
/// * [kProcessingSyncTask] — iOS BGProcessingTask: minutes of uploads while
///   the phone is idle (typically overnight on the charger). iOS only; the
///   system does not re-arm it, so the task re-schedules itself after each run.
/// * [kDrainSyncTask] — one-off "finish what's pending" task enqueued when the
///   app goes to the background with a real backlog. On Android it runs as a
///   dataSync foreground service: a quiet, low-priority notification is shown
///   ONLY while the backlog is draining and disappears when it is empty
///   (Android 14+ allows ~6 h/day of this). On iOS it is the standard ~30 s
///   background-task extension.
///
/// Whichever entry point fires, the background isolate first looks for the
/// running app (see [BackgroundSyncService.relayPortName]) and, if it is
/// alive, asks IT to do the uploading — the live sync engine has the database
/// open and all the in-process state. Only when the app process is gone does
/// the background isolate open the database itself and run [UploadService]
/// headlessly. The two never upload concurrently.
const String kPeriodicSyncTask = 'com.dartmouth.smerb.sync.periodic';
const String kProcessingSyncTask = 'com.dartmouth.smerb.sync.processing';
const String kDrainSyncTask = 'com.dartmouth.smerb.sync.drain';

/// Pure scheduling decisions, unit-tested.
class BackgroundSyncPlan {
  BackgroundSyncPlan._();

  /// Wall-clock budget one background run may spend uploading. The OS limits
  /// behind these: Android WorkManager stops a plain worker at 10 min, a
  /// foreground-service worker at ~6 h/day; iOS gives a refresh task ~30 s and
  /// a processing task a few minutes.
  static Duration budgetFor(String task, {required bool isIOS}) {
    switch (task) {
      case kDrainSyncTask:
        return isIOS ? const Duration(seconds: 20) : const Duration(minutes: 20);
      case kProcessingSyncTask:
        return const Duration(seconds: 150);
      case kPeriodicSyncTask:
        return isIOS ? const Duration(seconds: 20) : const Duration(minutes: 8);
      default:
        return const Duration(seconds: 20);
    }
  }

  /// Scale applied to [UploadService]'s per-stage budgets so one `syncAll`
  /// cycle (normally ~50 s of budget) fits inside a short run.
  static double budgetScale(Duration budget) {
    const normalCycleSeconds = 50;
    return math.min(1.0, budget.inMilliseconds / (normalCycleSeconds * 1000));
  }

  /// Leaving the app with this much unsent data starts a drain task (and, on
  /// Android, its notification). The pause-triggered `syncNow` already handles
  /// a handful of events in seconds; a notification for those would be noise.
  /// Check-in responses are never left waiting.
  static const int drainThreshold = 20;
  static bool shouldDrain({
    required int pendingEvents,
    required int pendingHtml,
    required int pendingEma,
  }) {
    if (pendingEma > 0) return true;
    return pendingEvents + pendingHtml >= drainThreshold;
  }
}

/// Result of a run, in both isolates. Serialisable (primitives only) so it can
/// cross the isolate boundary and be stored in an event.
class DrainSummary {
  int cycles = 0;
  final Map<String, int> synced = {};
  String stoppedBecause = 'drained';
  Map<String, int> pendingBefore = const {};
  Map<String, int> pendingAfter = const {};
  String? error;

  void add(Map<String, int> cycleResults) {
    cycles++;
    for (final e in cycleResults.entries) {
      if (e.key == 'truncated') continue;
      synced[e.key] = (synced[e.key] ?? 0) + e.value;
    }
  }

  /// Items that moved in [cycleResults] (bytes and the truncated flag excluded).
  static int progressIn(Map<String, int> cycleResults) => cycleResults.entries
      .where((e) => e.key != 'truncated' && e.key != 'bytesUploaded' && e.key != 'screenshots')
      .fold(0, (a, e) => a + e.value);

  Map<String, dynamic> toMap(String mode) => {
        'mode': mode,
        'cycles': cycles,
        'stoppedBecause': stoppedBecause,
        'pendingBefore': pendingBefore,
        'pendingAfter': pendingAfter,
        if (error != null) 'error': error,
        ...synced,
      };
}

/// Runs sync cycles until nothing is pending, the budget is spent, or a cycle
/// moves nothing (network down, writes rejected) — never spins. Shared by the
/// live engine (relay mode) and the headless runner; pure apart from its
/// callbacks, so it is unit-tested with fakes.
Future<DrainSummary> runDrainLoop({
  required Duration budget,
  required Future<Map<String, int>> Function() runCycle,
  required Future<Map<String, int>> Function() pending,
  Future<bool> Function()? isPaused,
  DateTime Function()? now,
}) async {
  final clock = now ?? DateTime.now;
  final started = clock();
  final summary = DrainSummary();
  summary.pendingBefore = await pending();
  try {
    while (true) {
      if (isPaused != null && await isPaused()) {
        summary.stoppedBecause = 'paused';
        break;
      }
      final p = summary.cycles == 0 ? summary.pendingBefore : await pending();
      if (p.values.fold(0, (a, b) => a + b) == 0) {
        summary.stoppedBecause = 'drained';
        break;
      }
      if (clock().difference(started) >= budget) {
        summary.stoppedBecause = 'budget';
        break;
      }
      final r = await runCycle();
      summary.add(r);
      if (DrainSummary.progressIn(r) == 0) {
        // A cycle that reports nothing may still have found an empty queue:
        // on iOS the wake-up fires the app's own 30 s timer first, that cycle
        // does the uploading, and the drain's cycle sees nothing left. Say
        // "drained", not "no_progress", when that is what happened.
        final left = await pending();
        summary.stoppedBecause =
            left.values.fold(0, (a, b) => a + b) == 0 ? 'drained' : 'no_progress';
        break;
      }
    }
  } catch (e) {
    summary.stoppedBecause = 'error';
    summary.error = e.toString().substring(0, math.min(300, e.toString().length));
  }
  summary.pendingAfter = await pending();
  return summary;
}

/// Everything a background run needs from the database, in one map.
Future<Map<String, int>> pendingUploadCounts(AppDatabase db) async => {
      'events': await db.getUnsyncedEventCount(),
      'html': await db.getPendingHtmlSyncCount(),
      'ema': await db.getUnsyncedEmaCount(),
      'ocr': await db.getUnsyncedOcrCount(),
    };

/// Leaves a `background_sync` event describing one run (only runs that found
/// work: idle wake-ups write nothing). Best-effort.
Future<void> recordBackgroundSyncEvent(
  AppDatabase db,
  String task,
  Map<String, dynamic> summary, {
  required Duration elapsed,
}) async {
  try {
    if ((summary['cycles'] as int? ?? 0) == 0 && summary['error'] == null) return;
    final pid = await ParticipantService().getParticipantId() ?? await db.getLatestParticipantId();
    if (pid == null) return;
    await db.insertEvent(EventsCompanion(
      id: Value(const Uuid().v4()),
      sessionId: const Value('system'),
      participantId: Value(pid),
      eventType: const Value('background_sync'),
      timestamp: Value(DateTime.now()),
      platform: Value(Platform.isIOS ? 'ios' : 'android'),
      data: Value(jsonEncode({
        'task': task.split('.').last,
        'durationMs': elapsed.inMilliseconds,
        ...summary,
      })),
    ));
  } catch (e) {
    print('[BackgroundUpload] could not record background_sync event: $e');
  }
}

/// Registers the OS-scheduled tasks and enqueues drains. Main isolate only.
class BackgroundUploadScheduler {
  BackgroundUploadScheduler._();

  static bool _initialized = false;

  /// Idempotent. Call once the participant is enrolled (there is nothing to
  /// upload before that). Re-registering on every launch is how constraint
  /// changes in a new app version reach the scheduler.
  static Future<void> ensureScheduled() async {
    if (kIsWeb) return;
    try {
      if (!_initialized) {
        await Workmanager().initialize(backgroundSyncDispatcher);
        _initialized = true;
      }
      await Workmanager().registerPeriodicTask(
        kPeriodicSyncTask,
        kPeriodicSyncTask,
        frequency: const Duration(minutes: 15),
        // iOS: earliest-begin hint for the first BGAppRefreshTask.
        initialDelay: const Duration(minutes: 15),
        constraints: Constraints(
          networkType: NetworkType.unmetered,
          requiresBatteryNotLow: true,
        ),
        existingWorkPolicy: ExistingPeriodicWorkPolicy.update,
      );
      if (Platform.isIOS) await scheduleProcessingTask();
      print('[BackgroundUpload] scheduled periodic sync'
          '${Platform.isIOS ? ' + processing task' : ''}');
    } catch (e) {
      // Never let scheduling break startup; foreground sync is unaffected.
      print('[BackgroundUpload] scheduling failed (non-fatal): $e');
    }
  }

  /// iOS BGProcessingTask. One-shot by design, so it is submitted again at
  /// the end of every run (from the background isolate) and at every launch.
  static Future<void> scheduleProcessingTask() async {
    if (!Platform.isIOS) return;
    try {
      await Workmanager().registerProcessingTask(
        kProcessingSyncTask,
        kProcessingSyncTask,
        initialDelay: const Duration(minutes: 30),
        constraints: Constraints(networkType: NetworkType.connected),
      );
    } catch (e) {
      print('[BackgroundUpload] processing task not scheduled: $e');
    }
  }

  /// The app is leaving the foreground with a backlog: keep uploading.
  static Future<void> requestDrain({required int pendingItems}) async {
    if (kIsWeb) return;
    try {
      await Workmanager().registerOneOffTask(
        kDrainSyncTask,
        kDrainSyncTask,
        inputData: {'pending': pendingItems},
        constraints: Constraints(networkType: NetworkType.connected),
        existingWorkPolicy: ExistingWorkPolicy.keep,
        // Android only: promote the worker to a dataSync foreground service
        // so the process survives in the background. The notification is
        // required by the OS while the service runs and is removed with it.
        foregroundServiceConfig: ForegroundServiceConfig(
          notificationTitle: 'SocialScope',
          notificationText: 'Uploading study data…',
          notificationChannelId: 'smerb_sync',
          notificationChannelName: 'Data upload',
          notificationId: 7741,
          foregroundServiceType: ForegroundServiceType.dataSync,
        ),
      );
      print('[BackgroundUpload] drain requested ($pendingItems pending)');
    } catch (e) {
      print('[BackgroundUpload] drain request failed (non-fatal): $e');
    }
  }

  /// The app is visible again: the live engine takes over and the
  /// notification (Android) goes away.
  static Future<void> cancelDrain() async {
    if (kIsWeb) return;
    try {
      await Workmanager().cancelByUniqueName(kDrainSyncTask);
    } catch (_) {}
  }
}

/// Entry point the OS calls in a background isolate (or, for iOS one-off
/// tasks, on the main isolate). Must be a top-level function and must never
/// be renamed without a migration: the callback handle is persisted.
@pragma('vm:entry-point')
void backgroundSyncDispatcher() {
  Workmanager().executeTask((task, inputData) async {
    final started = DateTime.now();
    final isIOS = Platform.isIOS;
    final budget = BackgroundSyncPlan.budgetFor(task, isIOS: isIOS);
    print('[BackgroundUpload] task $task started (budget ${budget.inSeconds}s)');
    try {
      DartPluginRegistrant.ensureInitialized();
      await _ensureFirebase();
      final summary = await BackgroundSyncRunner.run(task: task, budget: budget);
      print('[BackgroundUpload] task $task finished in '
          '${DateTime.now().difference(started).inSeconds}s: ${jsonEncode(summary)}');
    } catch (e, st) {
      print('[BackgroundUpload] task $task failed: $e\n$st');
    } finally {
      // iOS does not re-arm processing tasks.
      if (isIOS && task == kProcessingSyncTask) {
        await BackgroundUploadScheduler.scheduleProcessingTask();
      }
    }
    // Always "success": the periodic schedule IS the retry. Returning false
    // would make WorkManager back off exponentially.
    return true;
  });
}

/// `Firebase.apps` is per isolate, but the native FirebaseApp is per process.
/// Two background isolates starting together (seen: the periodic job and a
/// drain, 2026-11-24) can both find no Dart-side app and race to create the
/// native one; the loser gets "FirebaseApp name [DEFAULT] already exists".
/// A second call goes through initializeCore, which adopts the existing
/// native app instead of creating it.
Future<void> _ensureFirebase() async {
  if (Firebase.apps.isNotEmpty) return;
  for (var attempt = 1; ; attempt++) {
    try {
      await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
      return;
    } on FirebaseException catch (e) {
      if (e.code == 'duplicate-app') return;
      rethrow;
    } catch (e) {
      final text = e.toString();
      if (attempt < 3 && text.contains('already exists')) {
        await Future.delayed(const Duration(milliseconds: 300));
        continue;
      }
      rethrow;
    }
  }
}

/// Does the uploading for one background run, in whichever isolate can.
class BackgroundSyncRunner {
  BackgroundSyncRunner._();

  /// Registered by the headless runner while it holds the database, so a
  /// freshly launched app skips its own cycles until the run is over.
  static const String headlessPortName = 'com.dartmouth.smerb.sync.headless';

  static bool get headlessRunActive =>
      IsolateNameServer.lookupPortByName(headlessPortName) != null;

  /// True only if the isolate behind the name still answers. A name mapping
  /// outlives its isolate (WorkManager destroys the engine without running
  /// `finally` blocks when it stops a worker), and a stale one would make the
  /// app skip its own cycles for the rest of the process's life.
  static Future<bool> isHeadlessRunActive() async {
    final port = IsolateNameServer.lookupPortByName(headlessPortName);
    if (port == null) return false;
    final reply = ReceivePort();
    try {
      port.send({'cmd': 'ping', 'reply': reply.sendPort});
      await reply.first.timeout(const Duration(milliseconds: 1500));
      return true;
    } on TimeoutException {
      print('[BackgroundUpload] stale headless marker (isolate gone); clearing');
      IsolateNameServer.removePortNameMapping(headlessPortName);
      return false;
    } finally {
      reply.close();
    }
  }

  static Future<Map<String, dynamic>> run({required String task, required Duration budget}) async {
    final mainPort = IsolateNameServer.lookupPortByName(BackgroundSyncService.relayPortName);
    if (mainPort != null) return _relay(mainPort, task, budget);
    return _headless(task, budget);
  }

  /// The app is alive: ask its sync engine to drain and wait for the answer.
  static Future<Map<String, dynamic>> _relay(SendPort mainPort, String task, Duration budget) async {
    final reply = ReceivePort();
    try {
      mainPort.send({
        'cmd': 'drain',
        'task': task,
        'budgetMs': budget.inMilliseconds,
        'reply': reply.sendPort,
      });
      final answer = await reply.first.timeout(budget + const Duration(seconds: 90));
      if (answer is Map) return {'mode': 'relay', ...answer.cast<String, dynamic>()};
      return {'mode': 'relay', 'answer': answer.toString()};
    } on TimeoutException {
      return {'mode': 'relay', 'stoppedBecause': 'relay_timeout'};
    } finally {
      reply.close();
    }
  }

  /// The app process is gone: open the database and upload directly. No OCR
  /// here (its native channel lives on the main activity) and no cache
  /// housekeeping — just the upload stages, which are all that matter when
  /// nobody is using the phone.
  static Future<Map<String, dynamic>> _headless(String task, Duration budget) async {
    final started = DateTime.now();
    // The periodic job and a drain can both fire while the app is dead;
    // WorkManager would happily run them side by side in two isolates. One
    // uploader per process, always.
    if (headlessRunActive) {
      print('[BackgroundUpload] another headless run holds the database; skipping');
      return {'mode': 'headless', 'cycles': 0, 'stoppedBecause': 'another_run_active'};
    }
    final guard = ReceivePort();
    guard.listen((msg) {
      // Liveness probe from the app (see isHeadlessRunActive).
      if (msg is Map && msg['reply'] is SendPort) (msg['reply'] as SendPort).send('alive');
    });
    IsolateNameServer.registerPortWithName(guard.sendPort, headlessPortName);
    final db = AppDatabase();
    try {
      final upload = UploadService(database: db);
      final scale = BackgroundSyncPlan.budgetScale(budget);
      final summary = await runDrainLoop(
        budget: budget,
        runCycle: () => upload.syncAll(eventBatchSize: 25, ocrBatchSize: 25, budgetScale: scale),
        pending: () => pendingUploadCounts(db),
      );
      final map = summary.toMap('headless');
      await recordBackgroundSyncEvent(db, task, map, elapsed: DateTime.now().difference(started));
      // The summary event was written after the drain; push it now rather
      // than at the next run, so the dashboard sees this run promptly.
      try {
        await upload.syncEvents(batchSize: 10, budget: StageBudget(const Duration(seconds: 5)));
      } catch (_) {}
      return map;
    } finally {
      IsolateNameServer.removePortNameMapping(headlessPortName);
      guard.close();
      await db.close();
    }
  }
}
