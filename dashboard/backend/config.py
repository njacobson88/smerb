# SocialScope Dashboard Configuration

import os
from dotenv import load_dotenv

load_dotenv()

# Firebase project
FIREBASE_PROJECT_ID = "r01-redditx-suicide"

# Dartmouth IP ranges for whitelisting
# These are the official Dartmouth College IP ranges
# Dashboard only accessible from these IPs or via VPN
DARTMOUTH_IP_RANGES = [
    # Dartmouth main campus ranges
    "129.170.0.0/16",      # Primary Dartmouth range
    "132.177.0.0/16",      # Secondary Dartmouth range
    # VPN ranges (when connected to Dartmouth VPN)
    "10.0.0.0/8",          # Private VPN range
    # Local development
    "127.0.0.1/32",        # Localhost
    "::1/128",             # IPv6 localhost
]

# Allow bypass for local development (set DASHBOARD_DEV_MODE=true)
DEV_MODE = os.getenv("DASHBOARD_DEV_MODE", "false").lower() == "true"

# Dashboard settings
STUDY_START_DATE = "2025-01-01"
STUDY_LENGTH_DAYS = 90
EMA_PROMPTS_PER_DAY = 3

# Data indicators thresholds
SCREENSHOT_THRESHOLD_GOOD = 50  # screenshots per day for "good" status
SCREENSHOT_THRESHOLD_LOW = 10   # below this is "low" status
OCR_THRESHOLD_GOOD = 1000       # characters extracted per day
CHECKIN_THRESHOLD_GOOD = 2      # check-ins completed per day

# Server settings
HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

# Cache directory for exports
EXPORT_DIR = os.getenv("EXPORT_DIR", "/tmp/socialscope_exports")
EXPORT_TTL_SECONDS = 2 * 24 * 60 * 60  # 2 days

# Scheduler secret for automated cache refresh (set via environment variable)
SCHEDULER_SECRET = os.getenv("SCHEDULER_SECRET", "socialscope-scheduler-2026")
