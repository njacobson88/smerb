# SocialScope — Issues for Review (2026-03-24)

## Fixed During This Session

### Critical
- [x] FCM push notifications — added firebase_messaging, token registration, notification screen
- [x] canLaunchUrl silent failure — now shows fallback number for 988/Crisis Text
- [x] REDCap DET body parsing — was broken (sync asyncio in non-async function)
- [x] SMS reply commands — "ERROR" and "1" were missing from command map
- [x] Cloud Functions DASHBOARD_URL — broken self-reference fallback
- [x] getSyncStatus loading all rows — replaced with COUNT(*) queries

### Previously Fixed (earlier sessions)
- [x] Safety alerts fire-and-forget — now local-first with retry
- [x] Hardcoded phone number removed from safety alerts
- [x] Screenshot sync bug — don't mark synced if upload failed
- [x] Required questions enforced in check-in
- [x] Wake time hour overflow (% 24)
- [x] Zombie code removed (Riverpod, BaseEvent)
- [x] EMA responses uploaded as parsed object (not JSON string)

---

## Needs User Decision

### 1. Twilio Trial Account
**Status:** Trial accounts can only send to verified numbers.
**Action needed:** Upgrade to Pay-As-You-Go ($0.0079/SMS) for production with 800 participants.
**Impact:** All SMS/voice features (safety alerts, IVR, participant outreach) are blocked until upgraded.

### 2. Walk-Away Detection Performance
**Issue:** The escalation scheduler iterates ALL participants to check for unresolved pending confirmations every 5 minutes. With 800 participants, this will be slow.
**Options:**
  - A) Add a top-level `pending_confirmations` collection with just the unresolved ones (index-based, fast)
  - B) Accept the cost (it's a 5-min scheduler, a few seconds delay is acceptable)
  - C) Only check participants who had recent check-in activity

### 3. Print Statements in Production (133 total)
**Issue:** All print() calls in the Flutter app write to the system console in release builds. Contains participant IDs, session IDs, and safety alert data.
**Options:**
  - A) Replace all with kDebugMode guard
  - B) Replace with a proper logging package
  - C) Leave as-is (only visible via USB debug connection)

### 4. Check-in Window Persistence
**Issue:** Completed check-in windows are tracked in memory only. If the app restarts, previously completed windows show as incomplete.
**Impact:** Low — `alwaysAvailable: true` means windowed mode isn't active. But will matter when you activate scheduled windows.
**Fix when needed:** Persist completed window indices to SharedPreferences.

### 5. Data Pruning vs OCR Sync Race Condition
**Issue:** pruneOldSyncedData() deletes synced events, but OCR results reference events by eventId. If an event is pruned before its OCR result syncs, the OCR batch.update() will fail with NOT_FOUND.
**Options:**
  - A) Change OCR sync to use set() with merge instead of update()
  - B) Only prune events after verifying related OCR is also synced

### 6. SafetyAlert Model Unused Fields
**Issue:** SafetyAlert.threshold and SafetyAlert.triggerQuestions in ema_config.dart are parsed from JSON but never read — the per-question safetyTrigger config is used instead.
**Impact:** None (dead code, no functional issue).
**Fix:** Remove the unused fields, or use threshold as a default fallback.

### 7. REDCap Safety Plan Sync
**Status:** The safety plan screen exists and reads from Firestore, but no data is populated yet.
**Needed:** REDCap safety plan form needs to be finalized by Justine, then a sync script or Cloud Function to pull it into Firestore.

### 8. REDCap Device Type Sync
**Status:** The distribution panel allows manual device type selection, but no REDCap field has been created to store device type (iOS vs Android).
**Needed:** Add a field in REDCap for device type, then sync it into the participant's Firestore document. Manual override flag prevents overwriting.

### 9. Weekly Compliance Report Automation
**Status:** Weekly reports can be sent manually from the dashboard. No automation for Sunday delivery.
**Option:** Add a Cloud Scheduler job that runs Sundays at 10 AM ET, iterates all active participants, and sends the weekly report email. Would need a "send all" endpoint.

### 10. Firebase App Distribution Auto-Tester Add
**Status:** Testers can be added via the dashboard UI (per participant). No bulk import from REDCap.
**Option:** When REDCap DET fires for a new participant, auto-add their email as a tester.

---

## Monitoring Recommendations for Production

1. **Set up Firebase Crashlytics** — No crash reporting currently. Critical for 800 participants.
2. **Set up Cloud Monitoring alerts** — Alert on Cloud Run error rate, function failures.
3. **Test the full safety pipeline end-to-end** once Twilio is upgraded:
   - Trigger from app → SMS → IVR call → 988 handoff → escalation
4. **Rotate exposed credentials** — Twilio auth token, SendGrid API key were shared in conversation.
5. **Set up uptime monitoring** for the dashboard and backend URLs.
