# SocialScope — Issues for Review (2026-03-24)

## Fixed During This Session

### Critical/High
- [x] FCM push notifications — full implementation (service, token, notification screen)
- [x] canLaunchUrl silent failure — shows fallback number for 988/Crisis Text
- [x] REDCap DET body parsing — was completely broken (sync asyncio in async endpoint)
- [x] SMS reply commands — "ERROR" and "1" added to command map
- [x] Cloud Functions DASHBOARD_URL — broken self-reference fixed
- [x] getSyncStatus performance — COUNT queries replace row loading
- [x] Data pruning race condition — OCR/HTML sync uses set/merge
- [x] Walk-away notifications — 5-min was firing immediately, 10-min Timer died with process. Both now use zonedSchedule() which survives app termination
- [x] handled flag — confirmed danger alerts now correctly show as handled when participant outreach succeeds
- [x] Debug endpoints — gated behind dev mode (return 404 in production)
- [x] REDCap config warning — logs warning if API credentials not set
- [x] Compliance panel null crash — optional chaining fixed

### Previously Fixed (earlier sessions)
- [x] Safety alerts fire-and-forget → local-first with retry
- [x] Hardcoded phone number removed
- [x] Screenshot sync bug
- [x] Required questions enforced
- [x] Wake time hour overflow
- [x] Zombie code removed (Riverpod, BaseEvent)
- [x] EMA responses as parsed object

---

## Needs User Decision

### 1. Twilio Trial Account (BLOCKER for safety features)
**Status:** Trial accounts can only send to verified numbers.
**Action needed:** Upgrade to Pay-As-You-Go ($0.0079/SMS).
**Impact:** ALL SMS/voice features blocked until upgraded.

### 2. Enrollment Data Flow Gap
**Issue:** EnrollmentScreen doesn't receive uploadService, so participant doc in `participants` collection isn't created until first data sync. The participant IS in `valid_participants` immediately.
**Impact:** Low — dashboard checks both collections. But `participants/{id}` won't have enrollment metadata until sync starts.
**Fix:** Pass uploadService to EnrollmentScreen, or add explicit registerParticipant call after enrollment.

### 3. Walk-Away Detection Performance (800 participants)
**Issue:** Escalation scheduler iterates ALL participants to check pending confirmations every 5 min.
**Options:**
  - A) Add flag `hasPendingConfirmation` on participant doc, only query flagged participants
  - B) Use Firestore collection group query on `pending_safety_confirmations`
  - C) Accept cost (5-min scheduler, a few seconds is acceptable for safety)

### 4. Print Statements in Production (133 total)
**Issue:** All print() calls in Flutter app visible on device console.
**Options:**
  - A) Replace with kDebugMode guard
  - B) Replace with logging package
  - C) Leave as-is (only visible via USB)

### 5. REDCap DET Endpoint Security
**Issue:** Publicly accessible with no secret. Anyone who knows the URL can trigger ID generation.
**Fix:** Add a shared secret query parameter that REDCap includes in the DET URL.

### 6. REDCap Safety Plan Sync
**Status:** Screen exists but no data populated yet.
**Needed:** Justine finalizes form, then sync script to populate Firestore.

### 7. REDCap Device Type Sync
**Status:** Manual device type selection works. No REDCap field for auto-sync.
**Needed:** Add REDCap field, then sync on DET trigger.

### 8. Weekly Report Automation
**Status:** Manual send from dashboard works. No automated Sunday delivery.
**Option:** Add Cloud Scheduler for Sunday 10 AM ET batch send.

### 9. Firebase Crashlytics
**Status:** No crash reporting in production app.
**Action:** Add firebase_crashlytics package for production monitoring.

### 10. Credential Rotation
**Status:** Twilio auth token, SendGrid API key, and Twilio recovery code were shared in this conversation.
**Action:** Rotate all three before production use.

---

## Monitoring Recommendations
1. Set up Firebase Crashlytics
2. Set up Cloud Monitoring alerts for error rates
3. Test full safety pipeline end-to-end once Twilio upgraded
4. Set up uptime monitoring for dashboard + backend
5. Monitor Firestore read/write costs as participants scale
