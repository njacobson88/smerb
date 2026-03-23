# SocialScope Safety Features — Brainstorm & Technical Roadmap
## For 800-Participant Study with Active SI Monitoring

---

## Currently Implemented (as of 2026-03-22)

### App-Side Safety
- [x] Per-question safety confirmations with progressive wording (4 trigger questions)
- [x] Deliberate "Yes, I am in immediate danger" / "No" buttons (red/blue, hard to accidentally press)
- [x] Fallback alert when check-in abandoned with high-risk responses
- [x] Partial response saving on early exit
- [x] Crisis resources always accessible via toolbar icon
- [x] Personalized safety plan screen (6-step Stanley-Brown model)
- [x] Post-check-in resources shown when any SI threshold exceeded

### Backend Safety Infrastructure
- [x] On-call roster (primary / backup / PI) with dashboard management
- [x] Safety event audit trail with timestamped logging
- [x] Disposition logging (contacted_safe, escalated_988, escalated_er, etc.)
- [x] Time-to-human-contact tracking
- [x] Adverse event flagging
- [x] DSMB/IRB safety report generation
- [x] Automated follow-up schedule (24h / 48h / 72h / 7 days)
- [x] Follow-up completion logging with audit trail

### Notification & Outreach
- [x] Twilio SMS to on-call team (differentiated confirmed vs fallback)
- [x] Slack channel notification (email-to-channel)
- [x] Twilio IVR call to participant (press 1=safe, 2=team, 9=988)
- [x] SMS to participant ("we'll be calling")
- [x] Email to participant with crisis resources
- [x] Emergency contact SMS notification
- [x] 988 warm handoff via Twilio Dial
- [x] Escalation scheduler (15 min → backup, 30 min → PI)

---

## Brainstormed Future Features (prioritized by safety impact)

### Tier 1: High Safety Impact (implement before full enrollment)

#### 1. Passive SI Risk Detection from Browsing Content
**Concept:** Use the OCR-extracted text from screenshots to detect high-risk content exposure (e.g., suicidal content on Reddit/Twitter). If a participant is spending extended time on self-harm related content, generate a passive alert.
**Technical:** NLP classifier on extracted text, run during OCR processing. Flag patterns like extended exposure to r/SuicideWatch, crisis-related tweets, etc.
**NIMH Relevance:** Demonstrates passive safety monitoring beyond self-report.

#### 2. Missed Check-In Escalation
**Concept:** If a participant who previously endorsed SI (elevated scores) misses multiple consecutive check-ins, this could indicate deterioration. Auto-generate a wellness check alert.
**Technical:** Track check-in compliance per participant. If a participant with prior SI flags misses 2+ consecutive windows, create a low-priority safety event for team review.
**Implementation:** Backend scheduler that runs daily, cross-references SI history with check-in completion.

#### 3. Trend Detection & Early Warning
**Concept:** Track SI-related slider values over time. If a participant shows a significant upward trend (e.g., desire_intensity increasing over 3+ check-ins), flag for proactive outreach even if no single response exceeds the threshold.
**Technical:** Moving average of SI slider values. Alert when 3-session moving average crosses a lower threshold (e.g., 20) even if individual responses stay under 30.
**NIMH Relevance:** Longitudinal monitoring is a best practice for high-risk populations.

#### 4. App Health Monitoring
**Concept:** Monitor app-level signals that could indicate a participant is in trouble: app uninstalled, not opened for N days, background sync stopped. These could indicate withdrawal from the study or deterioration.
**Technical:** Cloud Function that checks last-sync timestamps for enrolled participants. Alert if no data received in 48+ hours.

#### 5. Geographic Safety Context (Optional, IRB-dependent)
**Concept:** If location permissions are granted, detect if participant is at a known high-risk location (e.g., bridge, parking garage roof) during a period of elevated SI scores.
**Note:** This has significant privacy implications and would need explicit IRB approval. List only as a research consideration.

### Tier 2: Operational Safety (improve reliability)

#### 6. Redundant Notification Channels
**Concept:** If Twilio SMS fails, fall back to email. If email fails, fall back to push notification to on-call person's phone. Ensure no single point of failure in the notification chain.
**Technical:** Add Firebase Cloud Messaging (FCM) as a tertiary channel. On-call staff install a simple companion app that receives push notifications.

#### 7. Automated Safety Protocol Compliance Checking
**Concept:** Auto-verify that the study protocol is being followed: every safety event has a disposition within 2 hours, follow-ups completed on schedule, on-call roster always has someone assigned.
**Technical:** Daily compliance check that generates a report card: X events responded to within SLA, Y follow-ups completed, Z gaps detected.

#### 8. Participant Communication Log
**Concept:** Centralized log of all outreach to each participant (calls, texts, emails) with outcomes. Prevents duplicate outreach and ensures continuity across team members.
**Technical:** Extend audit trail to include all communication attempts, not just safety-event-related ones.

#### 9. Real-Time Dashboard Safety View
**Concept:** Dedicated dashboard tab showing: live escalation status, on-call roster, pending follow-ups, compliance metrics. Replaces the current basic safety alerts list.
**Technical:** WebSocket or polling for real-time updates. Visual timeline of safety events.

### Tier 3: Research Quality & Reporting

#### 10. Automated DSMB Report Generation
**Concept:** Monthly automated report with: total safety events, response times, adverse events, participant attrition, protocol deviations. Export as PDF.
**Technical:** Scheduled Cloud Function that generates and emails the report.

#### 11. Comparative Safety Metrics
**Concept:** Track safety metrics against benchmark rates from similar studies. Flag if the study's SI rate is significantly above expected levels.
**Technical:** Configure benchmark rates. Statistical process control chart on the dashboard.

#### 12. Multi-Site Readiness
**Concept:** If the study expands to multiple sites, support site-specific on-call rosters, escalation chains, and reporting.
**Technical:** Add site_id to participant data and safety events. Site-scoped dashboard views.

---

## Audit Findings Summary

### Issues Found During Code Review:

1. **Unused import** in background_sync_service.dart: `package:flutter/foundation.dart` (warning-level, minor)

2. **Hardcoded phone number** in checkin_screen.dart: `pageTarget: '3143979832'` — should be moved to a config or removed since alert_recipients collection is the proper mechanism now

3. **No validation on slider response range** — slider values are stored as doubles but the safety trigger checks use `>` without clamping. Edge cases around exactly-threshold values should be considered.

4. **HtmlStatusLogs table growth** — even with 7-day pruning, at 1 row per 3 seconds (with new capture interval), this generates ~28K rows/day. The retention policy handles this but could be more aggressive for this table specifically.

5. **No app-level crash reporting** — if the app crashes during a safety-critical flow (e.g., mid-confirmation), there's no telemetry to detect it. Consider adding Firebase Crashlytics.

---

## Blockers for Going Live

| Feature | Blocker | Status |
|---------|---------|--------|
| Twilio SMS/calls | Need Twilio secrets set | Waiting on Twilio account setup |
| Slack/email alerts | Need MS Graph admin consent OR Gmail app password | IT ticket submitted |
| Crisis safety plan | Need Justine to finalize plan structure | In progress |
| Cloud Functions deploy | Need Twilio + Slack secrets before `firebase deploy --only functions` | Blocked |
| REDCap DET | Need to set DET URL in REDCap project settings | Ready once DET URL is configured |
| 988 warm handoff | Need 988 approval for Twilio voice integration | Contact submitted |
