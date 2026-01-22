#!/bin/bash

# SMERB App - Firebase App Distribution Setup Script
# This script will help you set up Firebase App Distribution and upload your APK

set -e

echo "==========================================="
echo "SMERB App - Firebase App Distribution Setup"
echo "==========================================="
echo ""

# Check if Firebase CLI is installed
if ! command -v firebase &> /dev/null; then
    echo "❌ Firebase CLI is not installed."
    echo "Installing Firebase CLI..."
    brew install firebase-cli
fi

echo "✅ Firebase CLI is installed (version $(firebase --version))"
echo ""

# Step 1: Login to Firebase
echo "Step 1: Logging in to Firebase..."
echo "This will open a browser window for authentication."
echo ""
firebase login

echo ""
echo "✅ Successfully logged in to Firebase"
echo ""

# Step 2: Initialize Firebase (if not already done)
if [ ! -f ".firebaserc" ]; then
    echo "Step 2: Setting up Firebase project..."
    echo "Please select or create a Firebase project for your app."
    echo ""
    firebase init
else
    echo "✅ Firebase project already configured"
    echo ""
fi

# Step 3: Upload APK to Firebase App Distribution
echo "Step 3: Uploading APK to Firebase App Distribution..."
echo ""

APK_PATH="build/app/outputs/flutter-apk/app-release.apk"

if [ ! -f "$APK_PATH" ]; then
    echo "❌ APK not found at $APK_PATH"
    echo "Building APK first..."
    flutter build apk --release
fi

echo "Uploading $APK_PATH to Firebase App Distribution..."
echo ""
echo "You'll need to provide:"
echo "  - App ID (e.g., 1:123456789:android:abcdef)"
echo "  - Tester groups or emails"
echo ""

# Upload to Firebase App Distribution
firebase appdistribution:distribute "$APK_PATH" \
    --app "\${FIREBASE_APP_ID}" \
    --release-notes "SMERB Research App - Reddit & Twitter/X Usage Tracking" \
    --groups "testers"

echo ""
echo "==========================================="
echo "✅ Setup Complete!"
echo "==========================================="
echo ""
echo "Your APK has been uploaded to Firebase App Distribution."
echo "Testers will receive an email with download instructions."
echo ""
echo "To upload future builds, run:"
echo "  flutter build apk --release"
echo "  firebase appdistribution:distribute build/app/outputs/flutter-apk/app-release.apk --app \${FIREBASE_APP_ID} --groups testers"
echo ""
