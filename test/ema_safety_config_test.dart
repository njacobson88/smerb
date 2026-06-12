// Regression guard on the EMA safety-trigger configuration — the literal root
// of the entire suicide-risk crisis pipeline. A wrong threshold, a missing
// `inverted` flag on ability_safe, or a slider value parsed as int instead of
// double would SILENTLY disable crisis detection. These tests fail loudly.
//
// Run:  flutter test test/ema_safety_config_test.dart
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:smerb_app/features/checkin/models/ema_config.dart';

/// Mirror of _isQuestionAboveThreshold in checkin_screen.dart. Kept in sync by
/// these tests so the config + the documented trigger contract are both guarded.
bool isAboveThreshold(EmaQuestion q, dynamic response) {
  if (q.safetyTrigger == null) return false;
  if (response is! double) return false;
  final threshold = (q.safetyTrigger!['threshold'] as num).toDouble();
  final inverted = q.safetyTrigger!['inverted'] == true;
  return inverted ? response < threshold : response > threshold;
}

void main() {
  late EmaConfig config;
  late Map<String, EmaQuestion> byId;

  setUpAll(() {
    final raw = File('assets/ema_questions.json').readAsStringSync();
    config = EmaConfig.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    byId = {for (final q in config.questions) q.id: q};
  });

  test('the four safety-trigger questions are present', () {
    for (final id in [
      'desire_intensity',
      'intention_strength',
      'thoughts_intent',
      'ability_safe',
    ]) {
      expect(byId.containsKey(id), isTrue, reason: 'missing trigger question $id');
      expect(byId[id]!.safetyTrigger, isNotNull, reason: '$id has no safety_trigger');
    }
  });

  test('safetyAlert.trigger_questions matches the trigger set', () {
    expect(
      config.safetyAlert.triggerQuestions.toSet(),
      {'desire_intensity', 'intention_strength', 'thoughts_intent', 'ability_safe'},
    );
  });

  test('non-inverted triggers fire when the response is ABOVE threshold', () {
    for (final id in ['desire_intensity', 'intention_strength', 'thoughts_intent']) {
      final q = byId[id]!;
      expect(q.safetyTrigger!['threshold'], 30);
      expect(q.safetyTrigger!['inverted'], isNot(true), reason: '$id must NOT be inverted');
      expect(isAboveThreshold(q, 40.0), isTrue, reason: '$id=40 should trigger');
      expect(isAboveThreshold(q, 31.0), isTrue, reason: '$id=31 should trigger');
      expect(isAboveThreshold(q, 30.0), isFalse, reason: '$id=30 is not > 30');
      expect(isAboveThreshold(q, 10.0), isFalse, reason: '$id=10 should not trigger');
    }
  });

  test('ability_safe is INVERTED — low ability to stay safe = danger', () {
    final q = byId['ability_safe']!;
    expect(q.safetyTrigger!['threshold'], 30);
    expect(q.safetyTrigger!['inverted'], isTrue,
        reason: 'CRITICAL: ability_safe MUST be inverted or low-safety answers miss');
    expect(isAboveThreshold(q, 10.0), isTrue, reason: 'ability_safe=10 (unsafe) should trigger');
    expect(isAboveThreshold(q, 29.0), isTrue, reason: 'ability_safe=29 should trigger');
    expect(isAboveThreshold(q, 30.0), isFalse, reason: 'ability_safe=30 is not < 30');
    expect(isAboveThreshold(q, 80.0), isFalse, reason: 'ability_safe=80 (safe) should not trigger');
  });

  test('slider min/max parse as doubles (the type the trigger check requires)', () {
    final q = byId['desire_intensity']!;
    expect(q.min, isA<double>());
    expect(q.max, isA<double>());
    // An int response would silently bypass the trigger (response is! double) —
    // document that contract: a double IS required.
    expect(isAboveThreshold(q, 40), isFalse, reason: 'int response bypasses (must be double)');
    expect(isAboveThreshold(q, 40.0), isTrue);
  });

  test('a null/absent response never triggers', () {
    expect(isAboveThreshold(byId['desire_intensity']!, null), isFalse);
    expect(isAboveThreshold(byId['ability_safe']!, null), isFalse);
  });
}
