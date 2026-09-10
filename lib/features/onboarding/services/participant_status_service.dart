import 'package:cloud_firestore/cloud_firestore.dart';
import '../../../core/config/environment_config.dart';

/// Whether this participant is still actively enrolled.
///
/// Coordinators mark participants inactive from the dashboard when they drop
/// out or finish. Until now the app never checked, so an "inactive" participant
/// kept browsing, capturing and receiving daily check-in reminders — the
/// reminders are scheduled locally on the device and repeat forever, so there
/// was no way to stop them, even past day 90.
class ParticipantStatus {
  final bool isActive;
  final String? reason;
  final bool resolved; // false when we could not read status (fail OPEN)

  const ParticipantStatus({
    required this.isActive,
    this.reason,
    this.resolved = true,
  });

  static const ParticipantStatus unknownActive =
      ParticipantStatus(isActive: true, resolved: false);
}

class ParticipantStatusService {
  /// Study length in days, matching the dashboard's 90-day window.
  static const int studyDurationDays = 90;

  /// Read the participant's status.
  ///
  /// Precedence matches the backend write path: `valid_participants` wins over
  /// `participants`, because that is the collection the dashboard writes to
  /// first. Any read failure returns [ParticipantStatus.unknownActive] — we
  /// FAIL OPEN so a network blip can never lock a participant out of the app
  /// (and out of the crisis resources it carries).
  Future<ParticipantStatus> fetch(String participantId) async {
    Map<String, dynamic> merged = {};
    var readAny = false;

    for (final col in ['participants', 'valid_participants']) {
      try {
        final snap = await FirebaseFirestore.instance
            .collection(EnvConfig.col(col))
            .doc(participantId)
            .get()
            .timeout(const Duration(seconds: 10));
        if (snap.exists) {
          readAny = true;
          (snap.data() ?? {}).forEach((k, v) {
            if (v != null) merged[k] = v;
          });
        }
      } catch (e) {
        print('[Status] read of $col failed: $e');
      }
    }

    if (!readAny) return ParticipantStatus.unknownActive;

    // An explicit researcher decision always wins.
    final manual = merged['manualActiveStatus'];
    if (manual is bool) {
      return ParticipantStatus(
        isActive: manual,
        reason: merged['manualActiveStatusReason'] as String?,
      );
    }

    // Otherwise fall back to the 90-day window.
    final start = _asDate(merged['studyStartDate']) ??
        _asDate(merged['enrolledAt']) ??
        _asDate(merged['createdAt']) ??
        _asDate(merged['created_at']);
    if (start != null) {
      final elapsed = DateTime.now().difference(start).inDays;
      if (elapsed > studyDurationDays) {
        return const ParticipantStatus(
            isActive: false, reason: 'Study period complete');
      }
    }
    return const ParticipantStatus(isActive: true);
  }

  static DateTime? _asDate(dynamic v) {
    if (v == null) return null;
    if (v is Timestamp) return v.toDate();
    if (v is DateTime) return v;
    if (v is String && v.length >= 10) {
      return DateTime.tryParse(v.substring(0, 10));
    }
    return null;
  }
}
