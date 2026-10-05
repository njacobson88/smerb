/**
 * Pure decision rules for the safety-escalation pipeline.
 *
 * Kept free of Firestore/Twilio so the rules that gate an IRREVERSIBLE action
 * (texting a participant's family that they are in crisis) can be unit tested
 * exhaustively. index.js calls these; nothing in here performs I/O.
 */

// Texting a participant's family/friends cannot be undone, so both paths wait
// out the window in which the participant can still say "that was an error"
// (reply ERROR/1, press 1, or tap error in the app) — any of which sets
// participantResolved and blocks the notification entirely.
const EMERGENCY_CONTACT_AFFIRMED_MIN = 10;    // they SAID they are in crisis
const EMERGENCY_CONTACT_UNREACHABLE_MIN = 30; // concerning answers, no reply on any channel

// Dispositions that establish the participant is okay. Any of these blocks
// contact notification outright, whichever path would otherwise apply.
const OK_DISPOSITIONS = new Set([
  "false_alarm",                 // ERROR/1/FALSE from participant or staff
  "contacted_safe",              // on-call reached them, they are safe
  "crisis_resolved_with_support", // IVR press 3: was in crisis, already supported
]);

// Dispositions meaning a human is actively handling it. These block the
// UNREACHABLE path (the premise "nobody can reach them" no longer holds) but
// not the AFFIRMATIVE path (the participant themselves said crisis).
// `unable_to_reach` is deliberately absent: on-call failing to reach them is
// MORE reason to text contacts, not less.
const HUMAN_HANDLING_DISPOSITIONS = new Set([
  "acknowledged",
  "contacted_needs_support",
  "escalated_988",
  "escalated_er",
  "ongoing",
]);

/**
 * Decide whether — and why — a participant's emergency contacts should be
 * texted for this safety event, given its current state.
 *
 * @returns {"affirmative"|"unreachable"|null}
 *   "affirmative" — participant affirmed a crisis (in-app YES, or IVR press 2)
 *   "unreachable" — concerning answers and no response on any channel
 *   null          — do not notify (yet, or ever)
 */
function emergencyContactReason(eventData, minutesSinceCreation, opts = {}) {
  const affirmedMin = opts.affirmedMin ?? EMERGENCY_CONTACT_AFFIRMED_MIN;
  const unreachableMin = opts.unreachableMin ?? EMERGENCY_CONTACT_UNREACHABLE_MIN;

  if (!eventData) return null;
  if (!Number.isFinite(minutesSinceCreation) || minutesSinceCreation < 0) return null;

  // Fires at most once per event, ever.
  if (eventData.emergencyContactsNotified === true) return null;

  // An explicit denial or resolution by the participant ends the question.
  if (eventData.participantResolved === true) return null;

  const disposition = eventData.currentDisposition || null;
  if (disposition && OK_DISPOSITIONS.has(disposition)) return null;

  const alertType = eventData.alertType || "confirmed_danger";
  const affirmed =
    eventData.participantConfirmedCrisis === true ||
    eventData.notifyEmergencyContacts === true ||
    alertType === "confirmed_danger";

  if (affirmed) {
    return minutesSinceCreation >= affirmedMin ? "affirmative" : null;
  }

  // Unreachable: only while nobody has established contact.
  if (disposition && HUMAN_HANDLING_DISPOSITIONS.has(disposition)) return null;
  return minutesSinceCreation >= unreachableMin ? "unreachable" : null;
}

/**
 * The SMS sent to one emergency contact.
 *
 * `reason` MUST match what actually happened — this is read by a third party
 * who will act on it, and the two situations are not the same claim:
 *   "affirmative" — the participant themselves said they are in crisis.
 *   "unreachable" — the participant gave concerning answers and could not be
 *                   reached. They have NOT said they are in crisis; telling a
 *                   contact they did would be a misstatement.
 *
 * The participant's study ID is never included: it is a study identifier and
 * has no business on a family member's phone.
 */
function buildEmergencyContactSms(reason, participantName, contactName) {
  const who = (participantName || "").trim() || "A participant in our study";
  const you = (contactName || "").trim();
  const intro =
    `This is the Social Media Wellness research study team at Dartmouth College. ` +
    `${who} is taking part in our study and has listed you${you ? ` (${you})` : ""} ` +
    `as an emergency contact.`;

  const situation = reason === "affirmative"
    ? ` They have indicated that they are currently experiencing a mental health crisis.`
    : ` They gave responses that concerned us and we have not been able to reach them.`;

  return intro + situation +
    ` Please check in with them.` +
    ` If you believe they are in immediate danger, call 911.` +
    ` You can also call or text the 988 Suicide & Crisis Lifeline.`;
}

module.exports = {
  EMERGENCY_CONTACT_AFFIRMED_MIN,
  EMERGENCY_CONTACT_UNREACHABLE_MIN,
  OK_DISPOSITIONS,
  HUMAN_HANDLING_DISPOSITIONS,
  emergencyContactReason,
  buildEmergencyContactSms,
};
