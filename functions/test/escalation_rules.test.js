/**
 * Regression tests for the emergency-contact decision rules.
 *
 * Texting a participant's family that they are in crisis cannot be undone.
 * The invariants here are the ones that must never regress:
 *   - an explicit denial NEVER results in a text
 *   - it fires at most once per event
 *   - the message's claim matches what actually happened
 *
 * Run: npm test  (from functions/)
 */
const test = require("node:test");
const assert = require("node:assert");
const {
  EMERGENCY_CONTACT_AFFIRMED_MIN: AFF,
  EMERGENCY_CONTACT_UNREACHABLE_MIN: UNR,
  emergencyContactReason: reason,
  buildEmergencyContactSms: sms,
} = require("../escalation_rules");

const confirmed = (extra = {}) => ({ alertType: "confirmed_danger", ...extra });
const walkaway = (extra = {}) => ({ alertType: "unresolved_walkaway", ...extra });
const incomplete = (extra = {}) => ({ alertType: "incomplete_checkin_fallback", ...extra });

// ---------------------------------------------------------------------------
// The invariant that matters most: a denial blocks everything, always.
// ---------------------------------------------------------------------------
test("explicit denial blocks notification on every path and at every time", () => {
  for (const build of [confirmed, walkaway, incomplete]) {
    for (const t of [0, AFF, UNR, UNR * 10]) {
      assert.strictEqual(reason(build({ participantResolved: true }), t), null,
        `${build().alertType} @${t}min with participantResolved`);
    }
  }
});

test("denial via IVR press 1 / SMS ERROR / app error all set the same field", () => {
  // Every denial channel in the backend writes participantResolved: true.
  // This test documents that contract; if a new channel forgets it, contacts
  // could be texted after the participant said it was a mistake.
  for (const via of ["ivr_press1_error", "sms", "app_push_error", "ivr_press3_resolved"]) {
    assert.strictEqual(
      reason(confirmed({ participantResolved: true, participantResolvedVia: via }), UNR * 2),
      null, via);
  }
});

test("an 'okay' disposition blocks both paths", () => {
  for (const d of ["false_alarm", "contacted_safe", "crisis_resolved_with_support"]) {
    assert.strictEqual(reason(confirmed({ currentDisposition: d }), UNR * 2), null, `affirmed ${d}`);
    assert.strictEqual(reason(walkaway({ currentDisposition: d }), UNR * 2), null, `walkaway ${d}`);
  }
});

// ---------------------------------------------------------------------------
// Once per event
// ---------------------------------------------------------------------------
test("fires at most once per event", () => {
  assert.strictEqual(reason(confirmed({ emergencyContactsNotified: true }), UNR * 2), null);
  assert.strictEqual(reason(walkaway({ emergencyContactsNotified: true }), UNR * 2), null);
});

// ---------------------------------------------------------------------------
// Affirmative path
// ---------------------------------------------------------------------------
test("in-app YES is affirmative after the grace window, not before", () => {
  assert.strictEqual(reason(confirmed(), AFF - 1), null);
  assert.strictEqual(reason(confirmed(), AFF), "affirmative");
  assert.strictEqual(reason(confirmed(), UNR * 3), "affirmative");
});

test("IVR press 2 (988 requested) on a walk-away is affirmative", () => {
  // The participant walked away, was called, and asked for 988. That is an
  // affirmation — and it must stay affirmative even after the 988 bridge
  // connects and escalationStopped flips, which drops the event from the
  // unresolved query but must not change what we tell the contact.
  const e = walkaway({ participantConfirmedCrisis: true, notifyEmergencyContacts: true,
                       escalationStopped: true, currentDisposition: "escalated_988" });
  assert.strictEqual(reason(e, AFF), "affirmative");
});

test("affirmative is not blocked by a human-handling disposition", () => {
  for (const d of ["acknowledged", "contacted_needs_support", "escalated_er", "ongoing"]) {
    assert.strictEqual(reason(confirmed({ currentDisposition: d }), AFF), "affirmative", d);
  }
});

// ---------------------------------------------------------------------------
// Unreachable path
// ---------------------------------------------------------------------------
test("walk-away with no response at all is unreachable after its window", () => {
  assert.strictEqual(reason(walkaway(), UNR - 1), null);
  assert.strictEqual(reason(walkaway(), UNR), "unreachable");
  assert.strictEqual(reason(incomplete(), UNR), "unreachable");
});

test("walk-away never becomes 'affirmative' just by waiting", () => {
  assert.strictEqual(reason(walkaway(), UNR * 10), "unreachable");
});

test("unreachable is blocked once a human is handling it", () => {
  for (const d of ["acknowledged", "contacted_needs_support", "escalated_988", "escalated_er", "ongoing"]) {
    assert.strictEqual(reason(walkaway({ currentDisposition: d }), UNR * 2), null, d);
  }
});

test("on-call logging NOREACH does not block unreachable — it is more reason", () => {
  assert.strictEqual(reason(walkaway({ currentDisposition: "unable_to_reach" }), UNR), "unreachable");
});

// ---------------------------------------------------------------------------
// Defensive inputs
// ---------------------------------------------------------------------------
test("missing alertType defaults to confirmed_danger (matches createSafetyEvent)", () => {
  assert.strictEqual(reason({}, AFF), "affirmative");
});

test("garbage inputs never notify", () => {
  assert.strictEqual(reason(null, AFF), null);
  assert.strictEqual(reason(undefined, AFF), null);
  assert.strictEqual(reason(confirmed(), NaN), null);
  assert.strictEqual(reason(confirmed(), -5), null);
  assert.strictEqual(reason(confirmed(), Infinity), null);
});

test("thresholds are overridable for the caller but default to the constants", () => {
  assert.strictEqual(reason(confirmed(), 2, { affirmedMin: 1 }), "affirmative");
  assert.strictEqual(reason(walkaway(), 5, { unreachableMin: 5 }), "unreachable");
  assert.ok(AFF < UNR, "unreachable must wait longer than affirmative");
});

// ---------------------------------------------------------------------------
// Message content: the claim must match the reason
// ---------------------------------------------------------------------------
test("affirmative message says the participant indicated a crisis", () => {
  const m = sms("affirmative", "Robin Gamble", "Yule");
  assert.match(m, /Robin Gamble is taking part in our study/);
  assert.match(m, /listed you \(Yule\) as an emergency contact/);
  assert.match(m, /indicated that they are currently experiencing a mental health crisis/);
  assert.match(m, /Please check in with them/);
  assert.match(m, /call 911/);
  assert.match(m, /988/);
});

test("unreachable message does NOT claim the participant indicated a crisis", () => {
  const m = sms("unreachable", "Robin Gamble", "Yule");
  assert.doesNotMatch(m, /indicated/);
  assert.doesNotMatch(m, /currently experiencing/);
  assert.match(m, /concerned us and we have not been able to reach them/);
  assert.match(m, /Please check in with them/);
});

test("message uses the participant-facing study name", () => {
  assert.match(sms("affirmative", "R", "Y"), /Social Media Wellness/);
  assert.doesNotMatch(sms("affirmative", "R", "Y"), /SocialScope/);
});

test("message never leaks a study ID and tolerates missing names", () => {
  const m = sms("affirmative", "", "");
  assert.match(m, /A participant in our study is taking part/);
  assert.doesNotMatch(m, /\d{9}/);
  assert.doesNotMatch(m, /\(\)/);          // no empty "(name)" parens
  assert.doesNotMatch(sms("affirmative", null, null), /null|undefined/);
});
