import 'package:flutter_test/flutter_test.dart';
import 'package:smerb_app/features/checkin/services/checkin_service.dart';
import 'package:smerb_app/features/sync/services/upload_service.dart';

void main() {
  group('StageBudget', () {
    test('unlimited never expires', () {
      final b = StageBudget.unlimited();
      expect(b.hasTime, isTrue);
      expect(b.exceeded, isFalse);
    });
    test('expires and records it', () async {
      final b = StageBudget(const Duration(milliseconds: 30));
      expect(b.hasTime, isTrue);
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(b.hasTime, isFalse);
      expect(b.exceeded, isTrue);
    });
  });

  group('resumeRescheduleDecision', () {
    const d = CheckinService.resumeRescheduleDecision;
    test('intact schedule on the same day -> no reschedule, no log', () {
      expect(d(lastScheduledDate: '2026-10-21', todayDate: '2026-10-21', pendingReminderIds: [0, 1, 2], expectedCount: 3), isNull);
    });
    test('never scheduled this session -> reschedule', () {
      expect(d(lastScheduledDate: null, todayDate: '2026-10-21', pendingReminderIds: [0, 1, 2], expectedCount: 3), isNotNull);
    });
    test('day rolled over -> reschedule', () {
      expect(d(lastScheduledDate: '2026-10-21', todayDate: '2026-10-22', pendingReminderIds: [0, 1, 2], expectedCount: 3), contains('date changed'));
    });
    test('a reminder vanished from the OS -> reschedule', () {
      expect(d(lastScheduledDate: '2026-10-21', todayDate: '2026-10-21', pendingReminderIds: [0, 2], expectedCount: 3), contains('2/3'));
    });
    test('pending query failed (empty) -> reschedule rather than trust', () {
      expect(d(lastScheduledDate: '2026-10-21', todayDate: '2026-10-21', pendingReminderIds: [], expectedCount: 3), isNotNull);
    });
    test('reminders disabled (expected 0) -> nothing to do', () {
      expect(d(lastScheduledDate: '2026-10-21', todayDate: '2026-10-21', pendingReminderIds: [], expectedCount: 0), isNull);
    });
  });
}
