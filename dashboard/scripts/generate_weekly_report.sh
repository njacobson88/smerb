#!/bin/bash
# SocialScope - Weekly Summary Report Generator
# Generates a summary report of all participants for the past week

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$(dirname "$SCRIPT_DIR")"
REPORTS_DIR="$DASHBOARD_DIR/reports"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default to last 7 days
END_DATE=$(date +%Y-%m-%d)
START_DATE=$(date -v-7d +%Y-%m-%d 2>/dev/null || date -d "7 days ago" +%Y-%m-%d)

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        --start-date)
            START_DATE="$2"
            shift 2
            ;;
        --end-date)
            END_DATE="$2"
            shift 2
            ;;
        --output-dir)
            REPORTS_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   SocialScope Weekly Report Generator     ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo -e "Report Period: ${GREEN}$START_DATE${NC} to ${GREEN}$END_DATE${NC}"
echo ""

mkdir -p "$REPORTS_DIR"

cd "$DASHBOARD_DIR/backend"

if [ ! -d "venv" ]; then
    echo -e "${RED}Error: Backend virtual environment not set up${NC}"
    exit 1
fi

source venv/bin/activate

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="$REPORTS_DIR/weekly_report_${START_DATE}_to_${END_DATE}_${TIMESTAMP}.txt"

python3 << PYTHON_SCRIPT > "$REPORT_FILE"
import os
from datetime import datetime, timedelta
from collections import defaultdict

import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
if not firebase_admin._apps:
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()

db = firestore.client()

start_date = datetime.strptime("$START_DATE", "%Y-%m-%d")
end_date = datetime.strptime("$END_DATE", "%Y-%m-%d")

print("=" * 60)
print("SOCIALSCOPE WEEKLY SUMMARY REPORT")
print("=" * 60)
print(f"Report Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)
print()

# Get all participants
participants_ref = db.collection("participants")
participants = list(participants_ref.stream())

print(f"Total Enrolled Participants: {len(participants)}")
print()

# Collect stats
total_screenshots = 0
total_emas = 0
total_reddit = 0
total_twitter = 0
crisis_count = 0
safety_alerts = 0

participant_stats = []

for participant_doc in participants:
    pid = participant_doc.id
    pdata = participant_doc.to_dict()

    # Get events
    events_ref = db.collection("participants").document(pid).collection("events")
    events_query = events_ref.where("capturedAt", ">=", start_date).where("capturedAt", "<=", end_date + timedelta(days=1))

    screenshots = 0
    reddit = 0
    twitter = 0

    for event_doc in events_query.stream():
        event = event_doc.to_dict()
        if event.get("type", "screenshot") == "screenshot":
            screenshots += 1
            platform = event.get("platform", "").lower()
            if platform == "reddit":
                reddit += 1
            elif platform in ("twitter", "x"):
                twitter += 1

    total_screenshots += screenshots
    total_reddit += reddit
    total_twitter += twitter

    # Get EMA responses
    emas = 0
    has_crisis = False
    try:
        ema_ref = db.collection("participants").document(pid).collection("ema_responses")
        ema_query = ema_ref.where("completedAt", ">=", start_date).where("completedAt", "<=", end_date + timedelta(days=1))

        for ema_doc in ema_query.stream():
            emas += 1
            ema = ema_doc.to_dict()
            responses = ema.get("responses", {})
            for key, value in responses.items():
                if isinstance(value, str) and value.lower() in ("yes", "true"):
                    if "crisis" in key.lower() or "harm" in key.lower():
                        has_crisis = True
    except Exception:
        pass

    total_emas += emas
    if has_crisis:
        crisis_count += 1

    # Get safety alerts
    alerts = 0
    try:
        alerts_ref = db.collection("participants").document(pid).collection("safety_alerts")
        alerts_query = alerts_ref.where("triggeredAt", ">=", start_date).where("triggeredAt", "<=", end_date + timedelta(days=1))
        alerts = len(list(alerts_query.stream()))
    except Exception:
        pass

    safety_alerts += alerts

    # Calculate compliance (expected: 3 EMAs per day for 7 days = 21)
    expected_emas = 7 * 3
    compliance = min(100, int((emas / expected_emas) * 100)) if expected_emas > 0 else 0

    participant_stats.append({
        "id": pid,
        "screenshots": screenshots,
        "reddit": reddit,
        "twitter": twitter,
        "emas": emas,
        "compliance": compliance,
        "crisis": has_crisis,
        "alerts": alerts,
    })

# Sort by compliance (lowest first for attention)
participant_stats.sort(key=lambda x: x["compliance"])

print("-" * 60)
print("AGGREGATE STATISTICS")
print("-" * 60)
print(f"Total Screenshots Captured:    {total_screenshots:,}")
print(f"  - Reddit:                    {total_reddit:,}")
print(f"  - Twitter/X:                 {total_twitter:,}")
print(f"Total EMA Check-ins:           {total_emas:,}")
print(f"Participants with Crisis Flag: {crisis_count}")
print(f"Total Safety Alerts:           {safety_alerts}")
print()

if crisis_count > 0 or safety_alerts > 0:
    print("!" * 60)
    print("ATTENTION REQUIRED")
    print("!" * 60)
    for p in participant_stats:
        if p["crisis"] or p["alerts"] > 0:
            flags = []
            if p["crisis"]:
                flags.append("CRISIS INDICATED")
            if p["alerts"] > 0:
                flags.append(f"{p['alerts']} SAFETY ALERT(S)")
            print(f"  {p['id']}: {', '.join(flags)}")
    print()

print("-" * 60)
print("PARTICIPANT COMPLIANCE (sorted by compliance, lowest first)")
print("-" * 60)
print(f"{'ID':<20} {'EMAs':<8} {'Compl%':<8} {'Reddit':<8} {'Twitter':<8} {'Shots':<10}")
print("-" * 60)

for p in participant_stats:
    crisis_flag = " *CRISIS*" if p["crisis"] else ""
    print(f"{p['id']:<20} {p['emas']:<8} {p['compliance']:<8} {p['reddit']:<8} {p['twitter']:<8} {p['screenshots']:<10}{crisis_flag}")

print()
print("=" * 60)
print("END OF REPORT")
print("=" * 60)
PYTHON_SCRIPT

echo -e "${GREEN}Report generated: $REPORT_FILE${NC}"
echo ""
cat "$REPORT_FILE"
