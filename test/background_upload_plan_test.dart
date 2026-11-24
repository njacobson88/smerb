import 'package:flutter_test/flutter_test.dart';
import 'package:smerb_app/features/sync/services/background_upload_scheduler.dart';

/// 2026-11-24: uploads that continue while the app is closed. The loop that
/// drives them must stop on its own — on an empty queue, on a spent budget,
/// and on a cycle that moves nothing — because the OS will otherwise kill it.
void main() {
  group('BackgroundSyncPlan', () {
    test('budgets stay inside what each OS grants', () {
      expect(BackgroundSyncPlan.budgetFor(kPeriodicSyncTask, isIOS: false), const Duration(minutes: 8));
      expect(BackgroundSyncPlan.budgetFor(kPeriodicSyncTask, isIOS: true), const Duration(seconds: 20));
      expect(BackgroundSyncPlan.budgetFor(kProcessingSyncTask, isIOS: true), const Duration(seconds: 150));
      expect(BackgroundSyncPlan.budgetFor(kDrainSyncTask, isIOS: false), const Duration(minutes: 20));
      expect(BackgroundSyncPlan.budgetFor(kDrainSyncTask, isIOS: true), const Duration(seconds: 20));
      expect(BackgroundSyncPlan.budgetFor('iOSPerformFetch', isIOS: true), const Duration(seconds: 20));
    });

    test('short budgets shrink the stage budgets; long ones leave them alone', () {
      expect(BackgroundSyncPlan.budgetScale(const Duration(seconds: 20)), closeTo(0.4, 1e-9));
      expect(BackgroundSyncPlan.budgetScale(const Duration(minutes: 8)), 1.0);
      expect(BackgroundSyncPlan.budgetScale(const Duration(seconds: 50)), 1.0);
    });

    test('a drain is worth a notification only for a real backlog, or any check-in', () {
      expect(BackgroundSyncPlan.shouldDrain(pendingEvents: 3, pendingHtml: 2, pendingEma: 0), isFalse);
      expect(BackgroundSyncPlan.shouldDrain(pendingEvents: 0, pendingHtml: 20, pendingEma: 0), isTrue);
      expect(BackgroundSyncPlan.shouldDrain(pendingEvents: 12, pendingHtml: 8, pendingEma: 0), isTrue);
      expect(BackgroundSyncPlan.shouldDrain(pendingEvents: 0, pendingHtml: 0, pendingEma: 1), isTrue);
    });
  });

  group('runDrainLoop', () {
    var t = DateTime(2026, 11, 24, 12);
    DateTime clock() => t;
    setUp(() => t = DateTime(2026, 11, 24, 12));

    test('runs cycles until the queue is empty and reports the totals', () async {
      var html = 45;
      final s = await runDrainLoop(
        budget: const Duration(minutes: 8),
        now: clock,
        pending: () async => {'events': 0, 'html': html, 'ema': 0, 'ocr': 0},
        runCycle: () async {
          final n = html.clamp(0, 20);
          html -= n;
          t = t.add(const Duration(seconds: 30));
          return {'htmlCaptures': n, 'events': 0, 'bytesUploaded': n * 125000, 'truncated': html > 0 ? 1 : 0};
        },
      );
      expect(s.cycles, 3);
      expect(s.synced['htmlCaptures'], 45);
      expect(s.synced.containsKey('truncated'), isFalse);
      expect(s.stoppedBecause, 'drained');
      expect(s.pendingBefore['html'], 45);
      expect(s.pendingAfter['html'], 0);
      expect(s.toMap('headless')['mode'], 'headless');
    });

    test('does nothing when nothing is pending', () async {
      var cycles = 0;
      final s = await runDrainLoop(
        budget: const Duration(minutes: 8),
        now: clock,
        pending: () async => {'events': 0, 'html': 0, 'ema': 0, 'ocr': 0},
        runCycle: () async {
          cycles++;
          return {'events': 0};
        },
      );
      expect(cycles, 0);
      expect(s.cycles, 0);
      expect(s.stoppedBecause, 'drained');
    });

    test('stops when the budget is spent, with work still pending', () async {
      final s = await runDrainLoop(
        budget: const Duration(seconds: 60),
        now: clock,
        pending: () async => {'events': 0, 'html': 1000, 'ema': 0, 'ocr': 0},
        runCycle: () async {
          t = t.add(const Duration(seconds: 25));
          return {'htmlCaptures': 20, 'truncated': 1};
        },
      );
      expect(s.cycles, 3); // 0 s, 25 s, 50 s start; 75 s is past the budget
      expect(s.stoppedBecause, 'budget');
      expect(s.synced['htmlCaptures'], 60);
    });

    test('a cycle that moves nothing ends the run (offline / rejected writes)', () async {
      var cycles = 0;
      final s = await runDrainLoop(
        budget: const Duration(minutes: 8),
        now: clock,
        pending: () async => {'events': 7, 'html': 0, 'ema': 0, 'ocr': 0},
        runCycle: () async {
          cycles++;
          return {'events': 0, 'htmlCaptures': 0, 'bytesUploaded': 0, 'screenshots': 0};
        },
      );
      expect(cycles, 1);
      expect(s.stoppedBecause, 'no_progress');
    });

    test('respects the privacy pause', () async {
      final s = await runDrainLoop(
        budget: const Duration(minutes: 8),
        now: clock,
        isPaused: () async => true,
        pending: () async => {'events': 0, 'html': 50, 'ema': 0, 'ocr': 0},
        runCycle: () async => fail('must not upload while paused'),
      );
      expect(s.cycles, 0);
      expect(s.stoppedBecause, 'paused');
    });

    test('a throwing cycle is reported, not propagated', () async {
      final s = await runDrainLoop(
        budget: const Duration(minutes: 8),
        now: clock,
        pending: () async => {'events': 0, 'html': 50, 'ema': 0, 'ocr': 0},
        runCycle: () async => throw StateError('database closed'),
      );
      expect(s.stoppedBecause, 'error');
      expect(s.error, contains('database closed'));
      expect(s.toMap('relay')['error'], isNotNull);
    });
  });
}
