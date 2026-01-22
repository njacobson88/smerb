# SMERB Development Roadmap

## Phase 1: MVP - Reddit Capture ✅ COMPLETE

**Status**: Code complete, ready for testing

**Deliverables**:
- [x] Flutter project structure
- [x] WebView with Reddit mobile
- [x] JavaScript DOM observer
- [x] Local SQLite storage
- [x] Debug console
- [x] iOS optimization

**Test Criteria**:
- [ ] App launches successfully
- [ ] Reddit loads and is browsable
- [ ] Events captured in real-time
- [ ] Debug console shows event data
- [ ] Export to JSON works

---

## Phase 2: Backend Integration (2-3 weeks)

### 2.1: Firebase Setup
- [ ] Create Firebase project
- [ ] Configure Firestore database
- [ ] Set up Firebase Authentication
- [ ] Create security rules
- [ ] Deploy Cloud Functions (optional)

### 2.2: Upload Service
- [ ] Create `UploadService` class
- [ ] Implement batch upload logic
- [ ] Add retry mechanism with exponential backoff
- [ ] WiFi preference handling
- [ ] Sync status provider (Riverpod)

### 2.3: Background Sync
- [ ] Integrate WorkManager
- [ ] Schedule periodic uploads (every 15 min)
- [ ] Handle offline mode
- [ ] Battery optimization

**Files to create**:
- `lib/features/sync/services/upload_service.dart`
- `lib/features/sync/services/sync_queue.dart`
- `lib/core/config/firebase_config.dart`

---

## Phase 3: Twitter/X Support (1-2 weeks)

### 3.1: JavaScript Observer
- [ ] Create `assets/js/x_observer.js`
- [ ] Implement selectors for Twitter/X
- [ ] Tweet capture logic
- [ ] Like/retweet detection
- [ ] Handle Twitter's infinite scroll

### 3.2: Flutter Integration
- [ ] Update `BrowserScreen` for dual platform
- [ ] Platform selector widget
- [ ] Tab management (Reddit + X)
- [ ] Update event models for Twitter data

**Files to create**:
- `assets/js/x_observer.js`
- `lib/features/browser/widgets/platform_selector.dart`

---

## Phase 4: Onboarding & Consent (1 week)

### 4.1: Enrollment Flow
- [ ] Create enrollment code entry screen
- [ ] Backend enrollment validation
- [ ] Device registration
- [ ] Token storage (secure)

### 4.2: IRB Consent
- [ ] Consent screen with full IRB text
- [ ] Signature/confirmation
- [ ] Store consent timestamp
- [ ] Export consent records

### 4.3: Tutorial
- [ ] App walkthrough
- [ ] Explain data collection
- [ ] Demo of recording indicator
- [ ] How to check sync status

**Files to create**:
- `lib/features/onboarding/screens/enrollment_screen.dart`
- `lib/features/onboarding/screens/consent_screen.dart`
- `lib/features/onboarding/screens/tutorial_screen.dart`

---

## Phase 5: Production Polish (1-2 weeks)

### 5.1: UI/UX Improvements
- [ ] Better loading states
- [ ] Error handling with user messages
- [ ] Sync status indicator (persistent)
- [ ] Settings screen (pause capture, data usage, etc.)
- [ ] About screen with study info

### 5.2: Performance Optimization
- [ ] Profile battery usage
- [ ] Optimize JavaScript injection timing
- [ ] Database query optimization
- [ ] Memory leak detection

### 5.3: Testing
- [ ] Unit tests for services
- [ ] Widget tests for screens
- [ ] Integration tests for capture flow
- [ ] Real device testing (multiple iOS versions)

### 5.4: Analytics & Monitoring
- [ ] Crashlytics integration
- [ ] Performance monitoring
- [ ] Upload success rate tracking
- [ ] User engagement metrics

---

## Phase 6: Pilot Deployment (2 weeks)

### 6.1: Internal Testing
- [ ] Deploy to Firebase App Distribution
- [ ] Test with 5-10 research team members
- [ ] Monitor data quality on backend
- [ ] Fix critical bugs
- [ ] Refine selectors if needed

### 6.2: Beta Testing
- [ ] Deploy to small group (10-20 participants)
- [ ] Monitor for crashes
- [ ] Collect user feedback
- [ ] Optimize upload frequency
- [ ] Validate data completeness

---

## Phase 7: Full Deployment (Ongoing)

### 7.1: Participant Enrollment
- [ ] Generate enrollment codes for 800 participants
- [ ] Create participant documentation
- [ ] Set up support channel
- [ ] Monitor enrollment rate

### 7.2: Monitoring & Maintenance
- [ ] Daily data quality checks
- [ ] Weekly selector updates (Reddit/X changes)
- [ ] Participant support
- [ ] Backend scaling as needed

### 7.3: Research Dashboard
- [ ] Admin panel for researchers
- [ ] Participant status overview
- [ ] Data export functionality
- [ ] Analytics and visualizations

---

## Future Enhancements (Post-Study)

### Advanced Features
- [ ] Video view tracking
- [ ] Ad exposure detection
- [ ] Sentiment analysis integration
- [ ] Cross-platform session linking
- [ ] Participant self-report integration

### Additional Platforms
- [ ] Instagram support
- [ ] TikTok support
- [ ] Facebook support

### Data Quality
- [ ] Screenshot capture (with consent)
- [ ] OCR for image-based content
- [ ] Link resolution (shortened URLs)
- [ ] Content categorization (ML-based)

---

## Critical Path Items

**Must-have before participant deployment**:
1. ✅ Reddit capture working
2. ⏳ Firebase backend operational
3. ⏳ Upload/sync reliable
4. ⏳ Consent flow IRB-compliant
5. ⏳ Privacy measures implemented
6. ⏳ Pilot testing successful

**Nice-to-have but not blockers**:
- Twitter/X support (can add mid-study)
- Advanced analytics
- Real-time monitoring dashboard
- Screenshot capture

---

## Risk Mitigation

### Technical Risks

**Risk**: Reddit/Twitter change DOM structure frequently
**Mitigation**:
- Remote config for selectors (fetch from backend)
- Weekly monitoring
- Quick update mechanism via OTA

**Risk**: App Store rejection
**Mitigation**:
- Use Firebase App Distribution (approved)
- Enterprise distribution if needed
- Clear research disclosure

**Risk**: Data upload failures
**Mitigation**:
- Robust retry logic
- Local storage buffer (7 days)
- Sync monitoring alerts

### Research Risks

**Risk**: Low participant compliance
**Mitigation**:
- Make app easy to use
- Regular reminders
- Incentive structure
- Support channel

**Risk**: Data quality issues
**Mitigation**:
- Pilot testing
- Automated quality checks
- Manual spot-checking
- Participant feedback loop

---

## Timeline Estimate

Assuming 1 developer working full-time:

- **Phase 1**: ✅ Complete (2 weeks)
- **Phase 2**: 3 weeks
- **Phase 3**: 2 weeks
- **Phase 4**: 1 week
- **Phase 5**: 2 weeks
- **Phase 6**: 2 weeks
- **Total**: ~10-12 weeks from now to participant deployment

With multiple developers or part-time work, adjust accordingly.

---

## Next Immediate Actions

1. **Test the MVP** (this week)
   - Run the app
   - Browse Reddit
   - Verify data capture
   - Export and inspect data

2. **Set up Firebase** (next week)
   - Create project
   - Configure Firestore
   - Test data upload

3. **Plan Phase 2** (after MVP validation)
   - Detailed backend design
   - Upload service implementation
   - Background sync strategy

---

## Success Metrics

### Technical Metrics
- Event capture rate: >95%
- Upload success rate: >99%
- Battery impact: <5% per hour
- Crash rate: <0.1%

### Research Metrics
- Participant retention: >80% at 90 days
- Data completeness: >90% of sessions
- Compliance rate: >85% daily usage

---

## Questions to Resolve

- [ ] Exact IRB consent language?
- [ ] Participant compensation structure?
- [ ] Study duration per participant?
- [ ] Required platforms (Reddit only? Reddit + X?)
- [ ] Data sharing with other researchers?
- [ ] Post-study data retention period?
