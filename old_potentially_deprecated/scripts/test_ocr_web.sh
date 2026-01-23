#!/bin/bash

# OCR Web Test Script
# This starts a simple web server to test Tesseract.js OCR

cd "$(dirname "$0")/../web"

echo "=========================================="
echo "  OCR Web Test Server"
echo "=========================================="
echo ""
echo "Starting server at: http://localhost:8080/ocr_test.html"
echo ""
echo "1. Open the URL above in your browser"
echo "2. Select a screenshot image"
echo "3. Click 'Extract Text' to test OCR"
echo ""
echo "Press Ctrl+C to stop the server"
echo "=========================================="
echo ""

# Start simple Python HTTP server
python3 -m http.server 8080
