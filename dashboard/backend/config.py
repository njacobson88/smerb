# SocialScope Dashboard Configuration
#
# Environment Variables (Required):
#   FIREBASE_PROJECT_ID   - Firebase project ID (e.g., "r01-redditx-suicide")
#   SCHEDULER_SECRET      - Secret token for scheduler endpoint authentication (required in production)
#
# Environment Variables (Optional):
#   DASHBOARD_DEV_MODE    - Set to "true" to bypass IP whitelist (local dev only)
#   DASHBOARD_HOST        - Server bind address (default: 0.0.0.0)
#   DASHBOARD_PORT        - Server port (default: 8080)
#   EXPORT_DIR            - Directory for temporary export files (default: /tmp/socialscope_exports)
#   STUDY_START_DATE      - Study start date for compliance calculations (default: 2025-01-01)
#   EMA_PROMPTS_PER_DAY   - Expected check-ins per day (default: 3)
#   CORS_ORIGINS          - Comma-separated list of allowed CORS origins (has defaults)
#   GOOGLE_APPLICATION_CREDENTIALS - Path to Firebase service account JSON (optional on Cloud Run)

import os
from dotenv import load_dotenv

load_dotenv()

# Firebase project ID - must match your Firebase console project
# REQUIRED: Set via FIREBASE_PROJECT_ID environment variable
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "r01-redditx-suicide")

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
STUDY_START_DATE = os.getenv("STUDY_START_DATE", "2025-01-01")  # Used for compliance calculations
EMA_PROMPTS_PER_DAY = int(os.getenv("EMA_PROMPTS_PER_DAY", "3"))  # Expected check-ins per day

# Server settings
HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

# Export settings
EXPORT_DIR = os.getenv("EXPORT_DIR", "/tmp/socialscope_exports")

# Scheduler authentication
# Used by Cloud Scheduler to trigger automated tasks
# REQUIRED in production: Set via SCHEDULER_SECRET environment variable
SCHEDULER_SECRET = os.getenv("SCHEDULER_SECRET")

# CORS allowed origins
# Can be overridden with comma-separated list via CORS_ORIGINS environment variable
# Default includes localhost for development and Firebase Hosting URLs for production
DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "https://socialscope-dashboard.web.app",
    "https://socialscope-dashboard.firebaseapp.com",
    "https://r01-redditx-suicide.web.app",
    "https://r01-redditx-suicide.firebaseapp.com",
]

# REDCap API integration
REDCAP_API_URL = os.getenv("REDCAP_API_URL")
REDCAP_API_TOKEN = os.getenv("REDCAP_API_TOKEN")
REDCAP_PROJECT_ID = os.getenv("REDCAP_PROJECT_ID")  # Optional: for verifying DET requests

# REDCap Data Entry Trigger configuration
# The instrument and field that triggers app ID generation
REDCAP_TRIGGER_INSTRUMENT = "qualify_for_study"
REDCAP_TRIGGER_FIELD = "subject_qualified"
REDCAP_TRIGGER_VALUE = "1"  # "Yes" in yesno field
REDCAP_APP_ID_FIELD = "socialscope_app_id"
REDCAP_TRIGGER_EVENT = "interview_arm_1"

def get_cors_origins():
    """Get CORS origins from environment or use defaults."""
    env_origins = os.getenv("CORS_ORIGINS")
    if env_origins:
        return [origin.strip() for origin in env_origins.split(",") if origin.strip()]
    return DEFAULT_CORS_ORIGINS
