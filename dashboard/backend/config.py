# SocialScope Dashboard Configuration
#
# Environment Variables:
#   DASHBOARD_DEV_MODE    - Set to "true" to bypass IP whitelist (local dev only)
#   DASHBOARD_HOST        - Server bind address (default: 0.0.0.0)
#   DASHBOARD_PORT        - Server port (default: 8080)
#   EXPORT_DIR            - Directory for temporary export files (default: /tmp/socialscope_exports)
#   SCHEDULER_SECRET      - Secret token for scheduler endpoint authentication
#   GOOGLE_APPLICATION_CREDENTIALS - Path to Firebase service account JSON (optional on Cloud Run)

import os
from dotenv import load_dotenv

load_dotenv()

# Firebase project ID - must match your Firebase console project
FIREBASE_PROJECT_ID = "r01-redditx-suicide"

# Dartmouth IP ranges for whitelisting
# Dashboard is only accessible from these IP ranges or via Dartmouth VPN
# Update these if Dartmouth's IP allocation changes
DARTMOUTH_IP_RANGES = [
    # Dartmouth main campus ranges
    "129.170.0.0/16",      # Primary Dartmouth range
    "132.177.0.0/16",      # Secondary Dartmouth range
    # VPN ranges (when connected to Dartmouth VPN)
    "10.0.0.0/8",          # Private VPN range
    # Local development
    "127.0.0.1/32",        # Localhost IPv4
    "::1/128",             # Localhost IPv6
]

# Development mode - bypasses IP whitelist
# WARNING: Never enable in production
DEV_MODE = os.getenv("DASHBOARD_DEV_MODE", "false").lower() == "true"

# Study configuration
STUDY_START_DATE = "2025-01-01"  # Used for compliance calculations
EMA_PROMPTS_PER_DAY = 3          # Expected check-ins per day for compliance %

# Server settings
HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

# Export settings
EXPORT_DIR = os.getenv("EXPORT_DIR", "/tmp/socialscope_exports")

# Scheduler authentication
# Used by Cloud Scheduler to trigger automated tasks
# Should be set as a Cloud Run environment variable in production
SCHEDULER_SECRET = os.getenv("SCHEDULER_SECRET", "socialscope-scheduler-2026")
