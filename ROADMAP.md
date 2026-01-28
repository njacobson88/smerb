# SocialScope Development Status

## Current Status: Production Ready

The SocialScope platform is feature-complete and deployed for the research study.

---

## Completed Features ✅

### Phase 1: Core Mobile App ✅
- [x] Flutter project structure with iOS and Android support
- [x] WebView browser with Reddit mobile support
- [x] WebView browser with X/Twitter support
- [x] JavaScript DOM observers for both platforms
- [x] Local SQLite storage (Drift ORM)
- [x] Debug console for development
- [x] iOS and Android optimization

### Phase 2: Backend Integration ✅
- [x] Firebase project configured (Firestore + Storage)
- [x] Firebase Authentication for dashboard
- [x] Firestore security rules (test mode - see Security Notes)
- [x] UploadService with batch upload logic
- [x] Retry mechanism with exponential backoff
- [x] BackgroundSyncService (30-second intervals)
- [x] Offline-first data handling

### Phase 3: Data Capture ✅
- [x] Screenshot capture on content change
- [x] Image change detection (hash-based)
- [x] On-device OCR (Apple Vision iOS, ML Kit Android)
- [x] HTML page capture with change detection
- [x] Event capture (page_view, scroll, content_exposure, interaction)
- [x] Platform-specific observers (Reddit, X/Twitter)

### Phase 4: Participant Experience ✅
- [x] Participant ID validation (test IDs + production 9-digit)
- [x] Device enrollment tracking
- [x] Platform login flows (Reddit, Twitter)
- [x] EMA check-in system (3x daily configurable windows)
- [x] Local notifications for check-in prompts
- [x] Configurable EMA questions (assets/ema_questions.json)

### Phase 5: Safety Monitoring ✅
- [x] SI screening in EMA responses
- [x] Automated safety alert generation
- [x] Real-time dashboard alerts
- [x] Crisis resource display
- [x] Safety protocol tracking

### Phase 6: Researcher Dashboard ✅
- [x] React-based dashboard deployed
- [x] FastAPI backend on Cloud Run
- [x] Overall study metrics view
- [x] Per-participant detail view
- [x] Day-level hourly breakdown
- [x] Screenshot preview with OCR text
- [x] Safety alerts panel with caching
- [x] Multi-level data export (metadata, OCR, screenshots)
- [x] User management (admin/user roles)
- [x] IP whitelist security (Dartmouth network)

---

## Deployment Status

| Component | Status | URL/Location |
|-----------|--------|--------------|
| Mobile App | Deployed | Firebase App Distribution |
| Firebase Backend | Deployed | r01-redditx-suicide project |
| Dashboard Frontend | Deployed | socialscope-dashboard.web.app |
| Dashboard API | Deployed | Cloud Run (us-central1) |

---

## Known Limitations & Future Improvements

### Security (High Priority)
- [ ] Update `firestore.rules` with proper authentication before scaling
- [ ] Implement rate limiting on dashboard API
- [ ] Add audit logging for data access

### Performance
- [ ] Optimize export for very large datasets (>10K events)
- [ ] Add database indexes for common query patterns
- [ ] Consider screenshot compression options

### Features (Nice to Have)
- [ ] Video view tracking
- [ ] Ad exposure detection
- [ ] Instagram/TikTok/Facebook support
- [ ] ML-based content categorization
- [ ] Participant self-report integration outside EMA

### Technical Debt
- [ ] Add comprehensive unit tests
- [ ] Add integration tests for capture flow
- [ ] Replace bare exception handlers with specific error handling
- [ ] Add structured logging throughout

---

## Architecture Overview

```
Mobile App (Flutter)
├── Capture Layer
│   ├── WebView with JS observers
│   ├── Screenshot service (change detection)
│   ├── OCR service (on-device)
│   └── HTML capture service
├── Storage Layer
│   └── SQLite (Drift ORM)
├── Sync Layer
│   ├── Upload service (batched)
│   └── Background sync (30s intervals)
└── User Flows
    ├── Onboarding/enrollment
    ├── EMA check-ins
    └── Safety protocols

Firebase Backend
├── Firestore
│   ├── participants/{id}/events
│   ├── participants/{id}/ema_responses
│   ├── participants/{id}/safety_alerts
│   ├── valid_participants
│   └── export_jobs
└── Cloud Storage
    ├── screenshots/
    └── html/

Dashboard (React + FastAPI)
├── Frontend (Firebase Hosting)
│   ├── Study overview
│   ├── Participant detail
│   ├── Day detail with screenshots
│   ├── Safety alerts
│   └── Data export
└── Backend (Cloud Run)
    ├── Firestore queries
    ├── Storage access
    ├── Export generation
    └── Safety alert caching
```

---

## Success Metrics

### Technical (Measured)
- Event capture rate: Target >95%
- Upload success rate: Target >99%
- Battery impact: Target <5% per hour
- Crash rate: Target <0.1%

### Research (To Be Measured)
- Participant retention: Target >80% at 90 days
- Data completeness: Target >90% of sessions
- EMA compliance rate: Target >85% daily

---

## Maintenance Notes

### Platform UI Changes
Reddit and X/Twitter may change their DOM structure. When this happens:
1. Open the platform in Chrome DevTools
2. Inspect the new element structure
3. Update selectors in `assets/js/reddit_observer.js` or `assets/js/x_observer.js`
4. Test in the app (no rebuild needed - JS is loaded at runtime)

### Database Schema Changes
After modifying `lib/features/storage/database/database.dart`:
```bash
dart run build_runner build --delete-conflicting-outputs
```
Update `schemaVersion` and add migration in `onUpgrade`.

### Dashboard Deployment
```bash
# Frontend only
firebase deploy --only hosting:dashboard

# Backend only
cd dashboard/backend
gcloud run deploy socialscope-dashboard-api --source . --region=us-central1

# Full deployment
./dashboard/scripts/deploy.sh
```

---

## Contact

For questions about the SocialScope platform, contact the research team at Dartmouth College.
