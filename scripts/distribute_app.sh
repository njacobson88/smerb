#!/bin/bash
# Build and distribute the SocialScope app via Firebase App Distribution.
# Usage: ./scripts/distribute_app.sh [dev|prod] [android|ios|both]
#
# Prerequisites:
#   - Firebase CLI installed and logged in
#   - Flutter SDK installed
#   - For iOS: Xcode with enterprise signing profile configured
#   - For Android: release signing configured in android/app/build.gradle

set -e

ENVIRONMENT=${1:-prod}
PLATFORM=${2:-both}

if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prod" ]]; then
  echo "Usage: $0 [dev|prod] [android|ios|both]"
  exit 1
fi

echo "======================================"
echo "Building SocialScope: $ENVIRONMENT ($PLATFORM)"
echo "======================================"

ANDROID_APP_ID="1:436153481478:android:cd39924bcf90a0ab9f8687"
IOS_APP_ID="1:436153481478:ios:4d04d2e6257b0f0d9f8687"
RELEASE_NOTES="SocialScope $ENVIRONMENT build $(date +%Y-%m-%d_%H%M)"

# Android APK
if [[ "$PLATFORM" == "android" || "$PLATFORM" == "both" ]]; then
  echo ""
  echo "--- Building Android APK ---"
  flutter build apk --release --dart-define=ENVIRONMENT=$ENVIRONMENT

  APK_PATH="build/app/outputs/flutter-apk/app-release.apk"
  if [[ -f "$APK_PATH" ]]; then
    echo "APK built: $APK_PATH ($(du -h "$APK_PATH" | cut -f1))"

    echo "Uploading to Firebase App Distribution..."
    firebase appdistribution:distribute "$APK_PATH" \
      --app "$ANDROID_APP_ID" \
      --release-notes "$RELEASE_NOTES" \
      --groups "testers"

    echo "Android distribution complete!"
  else
    echo "ERROR: APK not found at $APK_PATH"
    exit 1
  fi
fi

# iOS IPA
if [[ "$PLATFORM" == "ios" || "$PLATFORM" == "both" ]]; then
  echo ""
  echo "--- Building iOS IPA ---"

  # Check for ExportOptions.plist
  if [[ ! -f "ios/ExportOptions.plist" ]]; then
    echo "WARNING: ios/ExportOptions.plist not found."
    echo "Creating a template — you may need to update the teamID and provisioning profile."
  fi

  flutter build ipa --release --dart-define=ENVIRONMENT=$ENVIRONMENT \
    --export-options-plist=ios/ExportOptions.plist 2>&1 || {
    echo ""
    echo "IPA build failed. You may need to:"
    echo "  1. Open ios/Runner.xcworkspace in Xcode"
    echo "  2. Configure signing for enterprise distribution"
    echo "  3. Update ios/ExportOptions.plist with your team ID and provisioning profile"
    exit 1
  }

  IPA_PATH=$(find build/ios/ipa -name "*.ipa" | head -1)
  if [[ -n "$IPA_PATH" ]]; then
    echo "IPA built: $IPA_PATH ($(du -h "$IPA_PATH" | cut -f1))"

    echo "Uploading to Firebase App Distribution..."
    firebase appdistribution:distribute "$IPA_PATH" \
      --app "$IOS_APP_ID" \
      --release-notes "$RELEASE_NOTES" \
      --groups "testers"

    echo "iOS distribution complete!"
  else
    echo "ERROR: IPA not found in build/ios/ipa/"
    exit 1
  fi
fi

echo ""
echo "======================================"
echo "Distribution complete: $ENVIRONMENT ($PLATFORM)"
echo "======================================"
