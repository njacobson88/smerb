# SMERB Quick Start Guide

**Goal**: Get the app running in 5 minutes and validate Reddit data capture works.

---

## Step 1: Install Dependencies

```bash
cd smerb_app
flutter pub get
```

---

## Step 2: Generate Required Files

```bash
dart run build_runner build --delete-conflicting-outputs
```

This creates:
- `lib/features/storage/database/database.g.dart`
- `lib/features/capture/models/base_event.g.dart`

---

## Step 3: Configure iOS

1. **Open Info.plist**:
   ```bash
   open ios/Runner/Info.plist
   ```

2. **Add these entries** (before the final `</dict></plist>`):

   ```xml
   <key>NSAppTransportSecurity</key>
   <dict>
       <key>NSAllowsArbitraryLoads</key>
       <true/>
   </dict>
   ```

3. **Install pods**:
   ```bash
   cd ios && pod install && cd ..
   ```

---

## Step 4: Run the App

```bash
flutter run
```

**Or** open in Xcode:
```bash
open ios/Runner.xcworkspace
```

---

## Step 5: Test Data Capture

### A. Browse Reddit
1. App opens to `reddit.com`
2. You'll see a green "Recording" badge
3. Browse normally:
   - Scroll through feed
   - Click posts
   - Upvote/downvote

### B. Check Debug Console
1. Tap the **bug icon** (🐛) in top-right
2. You should see:
   - Total event count
   - Event chips by type (page_view, scroll, content_exposure, interaction)
   - List of captured events

### C. Inspect an Event
1. Tap any event to expand
2. Check the JSON data
3. Look for:
   - Post ID (e.g., `t3_abc123`)
   - Title and text content
   - Author, subreddit
   - Upvotes, comments

---

## Expected Results

After 30 seconds of browsing Reddit, you should have:
- ✅ 1-2 page_view events
- ✅ 10-30 scroll events
- ✅ 5-15 content_exposure events
- ✅ 0-5 interaction events (if you upvoted/clicked)

---

## Troubleshooting

### "No events captured"

**Check Xcode console** for:
```
[SMERB] Initializing Reddit observer...
[SMERB] Reddit observer initialized
[CaptureService] Captured event: page_view
```

If missing:
- Make sure you're on `reddit.com`
- Try reloading (tap refresh button)
- Check that `assets/js/reddit_observer.js` exists

### "Build failed"

**Clear and rebuild**:
```bash
flutter clean
flutter pub get
dart run build_runner build --delete-conflicting-outputs
```

### "Database errors"

**Delete app and reinstall**:
```bash
flutter clean
flutter run
```

---

## What's Next?

Once you've validated Reddit capture works:

1. **Export data to inspect**:
   - Debug Console → Menu → Export to JSON
   - Paste into text editor
   - Analyze the captured data

2. **Test edge cases**:
   - Visit different subreddits
   - Click into comments
   - Search for content
   - Check all events are captured

3. **Refine selectors** (if needed):
   - If Reddit changed their DOM
   - Update `assets/js/reddit_observer.js`
   - Just reload in app (no rebuild needed)

4. **Move to Phase 2**:
   - Add Twitter/X support
   - Build Firebase backend
   - Implement data upload

---

## Success Criteria

✅ App launches without errors
✅ Reddit loads in WebView
✅ JavaScript injection succeeds (check console)
✅ Events appear in Debug Console
✅ Event data includes post content (title, author, etc.)
✅ Can export data to JSON

If all ✅ are green, **your capture strategy works!** 🎉

---

## Common Console Logs (Expected)

```
[SMERB] Initializing Reddit observer...
[SMERB] Reddit observer initialized
[SMERB] Observing 10 posts
[SMERB] Content entered viewport: t3_abc123
[SMERB] Sent event: content_exposure
[CaptureService] Captured event: content_exposure (reddit)
```

---

## Need Help?

1. Check `README.md` for detailed documentation
2. Review JavaScript in `assets/js/reddit_observer.js`
3. Inspect database schema in `lib/features/storage/database/database.dart`
4. Look at event models in `lib/features/capture/models/base_event.dart`
