# SMERB - Social Media Exposure Research Browser

A Flutter application for capturing user interactions with Reddit (and Twitter/X) for mental health research.

## Project Status: MVP - Phase 1

**Goal**: Validate that we can capture meaningful data from Reddit's mobile web interface.

**What works**:
- ✅ WebView with Reddit mobile
- ✅ JavaScript injection for DOM observation
- ✅ Local SQLite storage
- ✅ Debug console to view captured events
- ✅ iOS optimization

**What's coming later**:
- ⏳ Firebase backend upload
- ⏳ Twitter/X support
- ⏳ Onboarding/consent flow
- ⏳ Production polish

---

## Setup Instructions

### Prerequisites

- Flutter SDK (3.0.0 or higher)
- Xcode (for iOS development)
- CocoaPods

### Installation

1. **Clone/Navigate to project**
   ```bash
   cd smerb_app
   ```

2. **Install dependencies**
   ```bash
   flutter pub get
   ```

3. **Generate code** (for Drift database and JSON serialization)
   ```bash
   dart run build_runner build
   ```

4. **iOS Configuration**

   Open `ios/Runner/Info.plist` and add the contents from `ios/Runner/Info.plist.additions.txt`:

   ```bash
   open ios/Runner/Info.plist
   ```

   Add the XML entries from the additions file.

5. **Install iOS dependencies**
   ```bash
   cd ios
   pod install
   cd ..
   ```

6. **Run the app**
   ```bash
   flutter run
   ```

---

## How to Test

### 1. Launch the App

The app will:
- Initialize the database
- Create a test participant session
- Show the browser screen

### 2. Browse Reddit

- The app opens `https://www.reddit.com`
- You'll see a green "Recording" indicator in the URL bar
- Browse Reddit normally:
  - Scroll through the feed
  - Click on posts
  - Upvote/downvote
  - Navigate to different subreddits

### 3. Check Captured Data

- Tap the **bug icon** (🐛) in the top-right
- This opens the **Debug Console**
- You should see:
  - Event counts by type
  - List of all captured events
  - Detailed event data (expandable)

### 4. Expected Events

You should see these event types:

- **page_view**: When a new page loads
- **scroll**: When you scroll (throttled to every 100ms)
- **content_exposure**: When a post is visible for >1 second
- **interaction**: When you upvote/downvote/click

### 5. Inspect Event Data

Expand any event to see:
- Event ID and session ID
- Timestamp
- Platform (reddit)
- URL
- Raw JSON data containing:
  - Post ID
  - Title and text content
  - Author, subreddit
  - Upvotes, comments
  - Media URLs

### 6. Export Data (Optional)

In the Debug Console:
- Tap the **3-dot menu** → **Export to JSON**
- All events are copied to clipboard
- Paste into a text editor to inspect

---

## Troubleshooting

### No events are being captured

**Check JavaScript injection**:
1. Open the browser
2. Check Xcode console for logs:
   - `[SMERB] Initializing Reddit observer...`
   - `[SMERB] Reddit observer initialized`
   - `[SMERB] Sent event: ...`

If you don't see these logs:
- Make sure you're on `reddit.com` (not old.reddit.com yet)
- Try reloading the page (tap refresh)
- Check that JavaScript is enabled in WebView

**Check Flutter bridge**:
- Look for `[CaptureService] Captured event: ...` in console
- If you see JS logs but not Flutter logs, the JavaScript channel might not be working

### Reddit shows "Try the App" banner

This is normal. The JavaScript should still work. You can:
- Dismiss the banner
- OR the selectors might need updating if Reddit changed their DOM

### Events captured but nothing in Debug Console

- Make sure the database was initialized
- Check for errors in console
- Try clearing data and restarting

### Build errors

**If `database.g.dart` is missing**:
```bash
dart run build_runner build --delete-conflicting-outputs
```

**If `base_event.g.dart` is missing**:
Same command as above.

**If pods fail**:
```bash
cd ios
rm -rf Pods Podfile.lock
pod install
cd ..
```

---

## Project Structure

```
lib/
├── main.dart                           # App entry point
│
├── core/
│   └── config/
│       └── capture_config.dart         # Capture settings
│
├── features/
│   ├── browser/
│   │   └── screens/
│   │       └── browser_screen.dart     # Main WebView
│   │
│   ├── capture/
│   │   ├── models/
│   │   │   └── base_event.dart         # Event models
│   │   └── services/
│   │       └── capture_service.dart    # Event processing
│   │
│   ├── storage/
│   │   └── database/
│   │       └── database.dart           # SQLite database
│   │
│   └── debug/
│       └── screens/
│           └── debug_screen.dart       # Debug console
│
└── assets/
    └── js/
        └── reddit_observer.js          # JavaScript injected into Reddit
```

---

## Next Steps (After MVP Validation)

Once you've confirmed data capture works:

1. **Add Twitter/X support**
   - Create `x_observer.js`
   - Add Twitter-specific selectors
   - Update browser to support both platforms

2. **Build Firebase backend**
   - Set up Firestore
   - Implement upload service
   - Add background sync

3. **Add onboarding**
   - Consent screen (IRB-compliant)
   - Enrollment code entry
   - Tutorial

4. **Production polish**
   - Better UI/UX
   - Error handling
   - Analytics

---

## Important Notes for Research

### Privacy Considerations

- Participant ID is currently hardcoded (`mvp_test_participant`)
- All data is stored locally in SQLite
- No data leaves the device yet
- Password fields are NOT captured

### Data Volume

For a typical browsing session (30 minutes):
- ~500-1000 events
- ~1-2 MB of data
- Events include full post content (text, scores, etc.)

### Reddit DOM Selectors

Reddit frequently updates their UI. The selectors in `reddit_observer.js` are current as of December 2024. If Reddit changes:

1. Open Reddit in Chrome
2. Inspect elements (F12)
3. Update `SELECTORS` in `reddit_observer.js`
4. No app rebuild needed - just reload in WebView

---

## Support

For questions or issues:
- Check console logs (Xcode or `flutter run`)
- Review the JavaScript in `assets/js/reddit_observer.js`
- Inspect the database schema in `lib/features/storage/database/database.dart`

---

## License

Research use only. Not for public distribution.
