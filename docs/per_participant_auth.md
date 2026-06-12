# Per-Participant Auth — closing the cross-participant read hole

## Problem
Firestore/Storage reads of `safety_plan`, `received_notifications`, the
`participants/{id}` root, `valid_participants`, and all Storage objects are
`allow read: if true` — world-readable. They're `if true` because participants
have no identity the rules can check: the app reads its own data without auth,
and there's nothing to scope it to.

Root cause: **the only credential today is *knowing* the participantId** — which
is typed in at enrollment (`enrollment_screen.dart`). The same knowledge that
lets the app read the data would let an attacker claim the identity, so a
per-participant rule is meaningless until enrollment carries a real secret.

## Target design (per-participant isolation)
1. **Secret at creation.** When a participant is created (REDCap DET / backend),
   generate a high-entropy one-time `enrollmentSecret` (`enrollment_auth.generate_enrollment_secret`).
   Store ONLY its hash (`enrollmentSecretHash`) on the `valid_participants` doc.
   Put the plaintext in the distribution invite (the channel that already
   delivers the participantId).
2. **Exchange for a token.** App enrollment posts `{participantId, secret}` to
   `POST /api/auth/enrollment-token`. Backend `verify_secret` against the stored
   hash; on success mints a Firebase **custom token** with `uid = participantId`
   (`firebase_admin.auth.create_custom_token`) and returns it. Plaintext secret
   is never persisted.
3. **App signs in.** `firebase_auth` (new dependency) `signInWithCustomToken`.
   Firebase persists the session; the app refreshes silently. Now every Firebase
   request carries `request.auth.uid == participantId`.
4. **Scope the reads.** Rules change exposed reads from `if true` to
   `if request.auth.uid == participantId` (Firestore) and the matching Storage
   path scoping. **Writes stay permissive** so the safety-critical alert-write
   path never depends on auth being healthy.
5. **One-time consumption.** Mark the secret used after first successful
   exchange (allow re-mint for the same device, or a PI-triggered reset for a
   re-install).

## Phased rollout (must be in this order — never flip rules first)
- **P0 (done):** `enrollment_auth.py` crypto + tests. Non-breaking.
- **P1:** Backend — generate+store the hash at creation; add the
  `/api/auth/enrollment-token` endpoint. Include the secret in the invite. Still
  non-breaking (nothing enforces auth yet).
- **P2:** App — add `firebase_auth`, exchange secret → custom token → sign in.
  Ship a build; **confirm fleet adoption** (all active devices on the auth build).
- **P3:** Tighten the exposed READ rules to per-participant. Writes unchanged.
  Old app versions lose in-app *reads* of safety_plan/notifications (degraded UX)
  but still write alerts — so a stale device can't cause a missed crisis.

## Failure modes / safety
- Auth only gates READS. Safety-alert WRITES remain `if true`, so a token/network
  failure degrades the participant's in-app view but never blocks crisis capture.
- If the token endpoint is down at enrollment, the app falls back to the current
  no-auth behavior until P3; after P3 it must retry/queue (reads degrade only).

## P1 status (built, dormant — no live behavior change)
- `enrollment_auth.py` — crypto + URL/message builders (+ tests).
- `mint_enrollment_token` — signs custom tokens with the SA key in
  `FIREBASE_SERVICE_ACCOUNT_KEY` (the Cloud Run default ADC app can't sign).
- `POST /api/participant/{id}/enrollment/send` — coordinator (re)issues the
  link, rotates the secret (stores only the hash), sends SMS (Twilio) + email
  (SendGrid). **Not auto-sent at creation** — nothing fires until a coordinator
  clicks it, and the link does nothing until the app handles `smerb://` (P2).
- `POST /api/auth/enrollment-token` — public, IP-exempt, rate-limited; verifies
  the secret, returns a custom token.
- Landing page `/enroll` (static) → `smerb://enroll?...` hand-off; secret stays
  in the URL fragment.
- Dashboard "Send Sign-in Link" button.
- Reusable secret (re-tap on device change); rotates only on resend.

## Delivery
- SMS via Twilio (live). Email via SendGrid — **requires `SENDGRID_API_KEY` to be
  set on the Cloud Run service** (not currently set; the same key the
  compliance-email feature needs).

## Exact P3 rule changeset (DO NOT APPLY until P2 app is on every active device)
`firestore.rules` — change READS only, leave WRITES as-is so crisis capture never
depends on auth:
- `match /participants/{participantId}`: `allow read: if true;`
  → `allow read: if request.auth != null && request.auth.uid == participantId;`
- `match /participants/{participantId}/safety_plan/{planId}`: `allow read: if true;`
  → `allow read: if request.auth != null && request.auth.uid == participantId;`
- `match /participants/{participantId}/received_notifications/{notifId}`: same change.
- Mirror all three for `dev_participants`.
- `valid_participants` read stays `if true` (no PHI; the enrollment-secret HASH
  is safe to expose at ~190-bit; the app reads it pre-auth to validate IDs).

`storage.rules` — scope reads, keep writes open:
- `screenshots/`, `html/`, `content_events/`: `allow read: if true;`
  → `allow read: if request.auth != null && request.auth.uid == participantId;`
  (keep `allow write: if true;`).
- **Verify first:** the dashboard must read screenshots via tokenized download
  URLs (which bypass rules), not raw paths — confirm before applying or
  researcher image viewing breaks.

## Decisions needed (PI / IRB)
1. **Delivery of the secret.** Recommended: embed it in the existing distribution
   invite link/email as a deep-link param so the participant never types it.
   Needs the invite template + IRB sign-off that the link carries a credential.
2. **Re-install / device change.** A new install needs a fresh token — allow the
   participant to re-trigger the invite, or a coordinator "reset enrollment
   secret" action in the dashboard.
3. **Residual co-participant risk** until P3 ships — acceptable interim? (App
   Check enforcement could blunt the open-internet exposure in the meantime.)
