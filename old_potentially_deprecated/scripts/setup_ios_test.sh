#!/bin/bash

echo "=========================================="
echo "  SMERB iOS Test Setup"
echo "=========================================="
echo ""

# Check for iOS simulators
SIMULATORS=$(xcrun simctl list devices 2>/dev/null | grep -E "iPhone|iPad" | head -1)

if [ -z "$SIMULATORS" ]; then
    echo "❌ No iOS simulators found!"
    echo ""
    echo "To download iOS simulators:"
    echo "  1. Open Xcode"
    echo "  2. Go to Xcode → Settings → Platforms"
    echo "  3. Click '+' and download 'iOS 17' or 'iOS 18'"
    echo "  4. Wait for download to complete"
    echo ""
    echo "Alternatively, connect a physical iOS device via USB."
    echo ""
    exit 1
fi

echo "✅ iOS simulators available"
echo ""

# Check tessdata
if [ -d "ios/Runner/tessdata" ] && [ -f "ios/Runner/tessdata/eng.traineddata" ]; then
    echo "✅ tessdata folder exists in ios/Runner/"
else
    echo "❌ tessdata not found. Copying..."
    mkdir -p ios/Runner/tessdata
    cp -r assets/tessdata/* ios/Runner/tessdata/
fi

echo ""
echo "=========================================="
echo "  MANUAL STEP REQUIRED - Add tessdata to Xcode"
echo "=========================================="
echo ""
echo "1. Open: ios/Runner.xcworkspace"
echo ""
echo "2. In Project Navigator, right-click 'Runner' folder"
echo ""
echo "3. Select 'Add Files to Runner...'"
echo ""
echo "4. Navigate to: ios/Runner/tessdata"
echo ""
echo "5. IMPORTANT - In the dialog:"
echo "   ☑ Create folder references (NOT 'Create groups')"
echo "   ☐ Copy items if needed (UNCHECK this)"
echo "   ☑ Add to targets: Runner"
echo ""
echo "6. Click 'Add'"
echo ""
echo "7. Verify: tessdata folder should appear BLUE (not yellow)"
echo ""
echo "=========================================="
echo ""
echo "After completing the above, run:"
echo "  flutter run -d 'iPhone'"
echo ""
