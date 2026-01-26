# SocialScope - Social Media Exposure Research Platform

A comprehensive research platform for studying social media usage patterns and their relationship to mental health outcomes. Built with Flutter for iOS, Firebase for backend services, and a React monitoring dashboard.

## Project Overview

SocialScope enables researchers to:
- **Capture social media browsing behavior** on Reddit and X/Twitter via in-app WebViews
- **Collect ecological momentary assessments (EMAs)** with configurable check-in prompts
- **Monitor participant safety** through automated SI (suicidal ideation) screening and alerts
- **Extract text content** from screenshots using on-device OCR (Apple Vision)
- **Monitor study progress** via a real-time researcher dashboard

**Developed at Dartmouth College** for IRB-approved mental health research studies.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        SocialScope Platform                      │
├─────────────────┬─────────────────────┬─────────────────────────┤
│   iOS App       │   Firebase Backend   │   Researcher Dashboard  │
│   (Flutter)     │   (Firestore/Storage)│   (React)               │
├─────────────────┼─────────────────────┼─────────────────────────┤
│ • WebView       │ • participants/     │ • Real-time monitoring  │
│ • Screenshots   │ • events/           │ • Safety alerts         │
│ • OCR           │ • ema_responses/    │ • Data export           │
│ • EMA Check-ins │ • safety_alerts/    │ • Compliance tracking   │
│ • Local DB      │ • Cloud Storage     │ • User management       │
└─────────────────┴─────────────────────┴─────────────────────────┘
```

---

## Features

### Mobile App (iOS)

- **Multi-platform social media capture**: Reddit and X/Twitter support
- **Screenshot capture**: Automatic screenshots when content changes (throttled to reduce storage)
- **On-device OCR**: Text extraction using Apple Vision framework
- **EMA check-ins**: 3x daily ecological momentary assessments
- **Safety monitoring**: Automated SI screening with configurable thresholds
- **Background sync**: Uploads data to Firebase when connected
- **Offline-first**: All data stored locally, synced when available
- **Participant onboarding**: ID validation, consent, and platform login

### Firebase Backend

- **Firestore**: Structured data storage for events, EMAs, and alerts
- **Cloud Storage**: Screenshot image storage
- **Authentication**: Firebase Auth for dashboard access
- **Real-time sync**: Live data updates to dashboard

### Researcher Dashboard

- **Overview**: Study-wide compliance and data collection metrics
- **Participant detail**: Per-participant daily summaries
- **Day detail**: Hourly breakdown with screenshot previews
- **Safety alerts**: Real-time SI alert monitoring with full EMA context
- **Data export**: Multi-level exports (metadata, OCR text, screenshots)
- **User management**: Admin controls for dashboard access

---

## Setup Instructions

### Prerequisites

- Flutter SDK 3.19+
- Xcode 15+ (for iOS development)
- Node.js 18+ (for dashboard)
- Firebase CLI
- CocoaPods

### 1. Clone and Install Dependencies

```bash
git clone <repository>
cd smerb_app

# Flutter dependencies
flutter pub get

# Generate code (Drift database, JSON serialization)
dart run build_runner build --delete-conflicting-outputs

# iOS dependencies
cd ios && pod install && cd ..
```

### 2. Firebase Configuration

1. Create a Firebase project at [console.firebase.google.com](https://console.firebase.google.com)
2. Enable Firestore, Storage, and Authentication
3. Download configuration files:
   - `ios/Runner/GoogleService-Info.plist`
   - `macos/Runner/GoogleService-Info.plist` (if needed)
4. Configure Firebase in the project:
   ```bash
   flutterfire configure
   ```

### 3. Dashboard Setup

```bash
cd dashboard/frontend
npm install
npm run build

cd ../backend
pip install -r requirements.txt
```

### 4. Run the App

```bash
# iOS Simulator
flutter run

# Or build for device
flutter build ios
```

### 5. Deploy Dashboard

```bash
# Frontend (Firebase Hosting)
firebase deploy --only hosting:dashboard

# Backend (Cloud Run)
cd dashboard/backend
gcloud run deploy socialscope-dashboard-api --source . --region=us-central1
```

---

## Project Structure

```
smerb_app/
├── lib/
│   ├── main.dart                    # App entry point
│   ├── firebase_options.dart        # Firebase configuration
│   │
│   ├── core/
│   │   └── config/
│   │       └── capture_config.dart  # Capture settings
│   │
│   ├── features/
│   │   ├── browser/                 # WebView browser
│   │   │   └── screens/
│   │   │       └── browser_screen.dart
│   │   │
│   │   ├── capture/                 # Data capture
│   │   │   ├── models/
│   │   │   └── services/
│   │   │       ├── capture_service.dart
│   │   │       └── screenshot_service.dart
│   │   │
│   │   ├── checkin/                 # EMA check-ins
│   │   │   ├── screens/
│   │   │   └── services/
│   │   │
│   │   ├── ocr/                     # Text extraction
│   │   │   └── services/
│   │   │       └── ocr_service.dart
│   │   │
│   │   ├── onboarding/              # Participant enrollment
│   │   │   ├── screens/
│   │   │   └── services/
│   │   │
│   │   ├── storage/                 # Local database
│   │   │   └── database/
│   │   │       └── database.dart
│   │   │
│   │   └── sync/                    # Firebase sync
│   │       └── services/
│   │           ├── upload_service.dart
│   │           └── background_sync_service.dart
│   │
│   └── assets/
│       └── js/
│           ├── reddit_observer.js   # Reddit DOM observer
│           └── x_observer.js        # X/Twitter DOM observer
│
├── dashboard/
│   ├── frontend/                    # React dashboard
│   │   └── src/
│   │       ├── SocialScope.js       # Main app & Export screen
│   │       ├── OverallScreen.js     # Study overview
│   │       ├── ParticipantDetailScreen.js
│   │       ├── DayDetailScreen.js
│   │       └── UserManagement.js
│   │
│   └── backend/                     # FastAPI backend
│       ├── main.py                  # API endpoints
│       ├── config.py                # Configuration
│       └── requirements.txt
│
├── ios/                             # iOS native code
├── macos/                           # macOS native code
├── firebase.json                    # Firebase configuration
├── firestore.rules                  # Security rules
└── firestore.indexes.json           # Database indexes
```

---

## Data Model

### Firestore Collections

```
participants/{participantId}
├── events/           # Screenshot and interaction events
├── ema_responses/    # EMA check-in responses
└── safety_alerts/    # Triggered SI alerts

valid_participants/   # Pre-registered participant IDs
dashboard_cache/      # Cached dashboard data
export_jobs/          # Async export job tracking
```

### Event Types

| Type | Description |
|------|-------------|
| `screenshot` | Captured screenshot with optional OCR text |
| `page_view` | URL navigation event |
| `scroll` | Scroll position changes |
| `content_exposure` | Post visible for >1 second |
| `interaction` | Upvote, downvote, click actions |

---

## EMA Configuration

Check-ins are prompted 3 times daily at configurable windows:
- Morning (9 AM - 12 PM)
- Afternoon (2 PM - 5 PM)
- Evening (7 PM - 10 PM)

Each check-in includes:
- Mood and affect scales
- Social media usage questions
- SI screening items (when indicated)

---

## Safety Monitoring

The app includes automated safety monitoring:

1. **SI Screening**: Triggered by elevated responses on mood items
2. **Safety Alerts**: Generated when SI thresholds are exceeded
3. **Dashboard Alerts**: Real-time notification to researchers
4. **Response Tracking**: Records safety protocol responses

---

## Dashboard Access

The researcher dashboard is available at: `https://socialscope-dashboard.web.app`

### User Roles
- **Admin**: Full access including user management
- **User**: View-only access to participant data

### Export Levels
1. **Level 1**: Metadata + EMA responses + Safety alerts
2. **Level 2**: Level 1 + Events with OCR text
3. **Level 3**: Level 2 + Screenshot images (large files)

---

## Development

### Running Tests

```bash
flutter test
```

### Code Generation

After modifying database schema or JSON models:
```bash
dart run build_runner build --delete-conflicting-outputs
```

### Updating JavaScript Observers

The DOM observers in `assets/js/` may need updates when platforms change their UI:

1. Open the platform in Chrome DevTools
2. Inspect the new element structure
3. Update selectors in the observer file
4. Test in the app (no rebuild needed)

---

## Security & Privacy

- All data is encrypted in transit (HTTPS/TLS)
- Firebase Security Rules restrict data access
- Dashboard requires Dartmouth authentication
- Participant IDs are anonymized
- No personally identifiable information in event data
- Password fields are excluded from capture

---

## Troubleshooting

### Build Errors

**Missing generated files:**
```bash
dart run build_runner build --delete-conflicting-outputs
```

**Pod install failures:**
```bash
cd ios
rm -rf Pods Podfile.lock
pod install
```

### Data Not Syncing

1. Check network connectivity
2. Verify Firebase configuration
3. Check Xcode console for sync errors
4. Ensure participant is enrolled

### Dashboard Issues

1. Clear browser cache (Cmd+Shift+R)
2. Check Cloud Run logs for API errors
3. Verify Firestore indexes are created

---

## License

Research use only. Developed at Dartmouth College.

For questions, contact the research team.
