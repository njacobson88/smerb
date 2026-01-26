#!/bin/bash
# SocialScope - Crisis Flag Checker
# Quickly check for any participants who indicated "Yes" to crisis questions
# This script is designed for quick daily checks

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default to today
CHECK_DATE=${1:-$(date +%Y-%m-%d)}

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   SocialScope Crisis Flag Check           ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo -e "Checking date: ${GREEN}$CHECK_DATE${NC}"
echo ""

cd "$DASHBOARD_DIR/backend"

if [ ! -d "venv" ]; then
    echo -e "${RED}Error: Backend virtual environment not set up${NC}"
    exit 1
fi

source venv/bin/activate

python3 << PYTHON_SCRIPT
import os
from datetime import datetime, timedelta

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

check_date = datetime.strptime("$CHECK_DATE", "%Y-%m-%d")
next_date = check_date + timedelta(days=1)

print("Scanning EMA responses for crisis indicators...")
print()

# Get all participants
participants_ref = db.collection("participants")
participants = list(participants_ref.stream())

crisis_found = []
safety_alerts_found = []

for participant_doc in participants:
    pid = participant_doc.id

    # Check EMA responses for crisis
    try:
        ema_ref = db.collection("participants").document(pid).collection("ema_responses")
        ema_query = ema_ref.where("completedAt", ">=", check_date).where("completedAt", "<", next_date)

        for ema_doc in ema_query.stream():
            ema = ema_doc.to_dict()
            completed_at = ema.get("completedAt")

            if hasattr(completed_at, 'timestamp'):
                ts = datetime.fromtimestamp(completed_at.timestamp())
            else:
                ts = completed_at

            responses = ema.get("responses", {})
            for key, value in responses.items():
                if isinstance(value, str) and value.lower() in ("yes", "true"):
                    if "crisis" in key.lower() or "harm" in key.lower() or "hurt" in key.lower():
                        crisis_found.append({
                            "participant": pid,
                            "time": ts.strftime("%H:%M:%S") if ts else "Unknown",
                            "question": key,
                            "response": value,
                        })
    except Exception:
        pass

    # Check safety alerts
    try:
        alerts_ref = db.collection("participants").document(pid).collection("safety_alerts")
        alerts_query = alerts_ref.where("triggeredAt", ">=", check_date).where("triggeredAt", "<", next_date)

        for alert_doc in alerts_query.stream():
            alert = alert_doc.to_dict()
            triggered_at = alert.get("triggeredAt")

            if hasattr(triggered_at, 'timestamp'):
                ts = datetime.fromtimestamp(triggered_at.timestamp())
            else:
                ts = triggered_at

            safety_alerts_found.append({
                "participant": pid,
                "time": ts.strftime("%H:%M:%S") if ts else "Unknown",
                "handled": alert.get("handled", False),
            })
    except Exception:
        pass

# Report findings
if crisis_found:
    print("\033[91m" + "!" * 60 + "\033[0m")
    print("\033[91mCRISIS FLAGS DETECTED\033[0m")
    print("\033[91m" + "!" * 60 + "\033[0m")
    print()
    for c in crisis_found:
        print(f"  Participant: \033[91m{c['participant']}\033[0m")
        print(f"  Time: {c['time']}")
        print(f"  Question: {c['question']}")
        print(f"  Response: {c['response']}")
        print()
else:
    print("\033[92mNo crisis flags detected for this date.\033[0m")
    print()

if safety_alerts_found:
    print("\033[93m" + "-" * 60 + "\033[0m")
    print("\033[93mSAFETY ALERTS\033[0m")
    print("\033[93m" + "-" * 60 + "\033[0m")
    print()
    for a in safety_alerts_found:
        status = "Handled" if a["handled"] else "\033[91mUNHANDLED\033[0m"
        print(f"  Participant: {a['participant']}")
        print(f"  Time: {a['time']}")
        print(f"  Status: {status}")
        print()
else:
    print("\033[92mNo safety alerts for this date.\033[0m")
    print()

# Summary
total_issues = len(crisis_found) + len(safety_alerts_found)
if total_issues > 0:
    print("\033[91m" + "=" * 60 + "\033[0m")
    print(f"\033[91mTOTAL ISSUES REQUIRING ATTENTION: {total_issues}\033[0m")
    print("\033[91m" + "=" * 60 + "\033[0m")
else:
    print("\033[92m" + "=" * 60 + "\033[0m")
    print("\033[92mALL CLEAR - No issues detected\033[0m")
    print("\033[92m" + "=" * 60 + "\033[0m")
PYTHON_SCRIPT
