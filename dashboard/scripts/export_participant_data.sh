#!/bin/bash
# SocialScope - Export Participant Data Script
# Exports all data for a specific participant from Firestore

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$(dirname "$SCRIPT_DIR")"
EXPORT_DIR="$DASHBOARD_DIR/exports"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Usage
usage() {
    echo "Usage: $0 <participant_id> [options]"
    echo ""
    echo "Options:"
    echo "  --start-date YYYY-MM-DD   Filter by start date"
    echo "  --end-date YYYY-MM-DD     Filter by end date"
    echo "  --output-dir DIR          Output directory (default: $EXPORT_DIR)"
    echo "  --format FORMAT           Output format: json, csv (default: json)"
    echo "  --include-screenshots     Include screenshot URLs"
    echo ""
    echo "Examples:"
    echo "  $0 abc123"
    echo "  $0 abc123 --start-date 2024-01-01 --end-date 2024-01-31"
    echo "  $0 abc123 --format csv --output-dir ~/Downloads"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

PARTICIPANT_ID="$1"
shift

# Parse options
START_DATE=""
END_DATE=""
OUTPUT_DIR="$EXPORT_DIR"
FORMAT="json"
INCLUDE_SCREENSHOTS=false

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
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --format)
            FORMAT="$2"
            shift 2
            ;;
        --include-screenshots)
            INCLUDE_SCREENSHOTS=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            ;;
    esac
done

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   SocialScope Data Export                 ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo -e "Participant ID: ${GREEN}$PARTICIPANT_ID${NC}"
[ -n "$START_DATE" ] && echo -e "Start Date: $START_DATE"
[ -n "$END_DATE" ] && echo -e "End Date: $END_DATE"
echo -e "Output Format: $FORMAT"
echo -e "Output Directory: $OUTPUT_DIR"
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Check if API is running
API_URL="http://localhost:8080"
if ! curl -s "$API_URL/health" > /dev/null 2>&1; then
    echo -e "${YELLOW}Warning: API server not running at $API_URL${NC}"
    echo "Starting export via direct Firestore access..."
    echo ""

    # Use Python for direct Firestore export
    cd "$DASHBOARD_DIR/backend"

    if [ ! -d "venv" ]; then
        echo -e "${RED}Error: Backend virtual environment not set up${NC}"
        echo "Run 'cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt'"
        exit 1
    fi

    source venv/bin/activate

    python3 << PYTHON_SCRIPT
import json
import os
import sys
from datetime import datetime
from pathlib import Path

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

participant_id = "$PARTICIPANT_ID"
start_date = "$START_DATE" if "$START_DATE" else None
end_date = "$END_DATE" if "$END_DATE" else None
output_dir = Path("$OUTPUT_DIR")

print(f"Exporting data for participant: {participant_id}")

# Get participant document
participant_ref = db.collection("participants").document(participant_id)
participant_doc = participant_ref.get()

if not participant_doc.exists:
    print(f"Error: Participant {participant_id} not found")
    sys.exit(1)

participant_data = participant_doc.to_dict()

# Export events
events_ref = participant_ref.collection("events")
events_query = events_ref.order_by("capturedAt")

if start_date and end_date:
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    events_query = events_ref.where("capturedAt", ">=", start_dt).where("capturedAt", "<=", end_dt)

events_data = []
for event_doc in events_query.stream():
    event = event_doc.to_dict()
    captured_at = event.get("capturedAt")
    if captured_at and hasattr(captured_at, 'timestamp'):
        event["capturedAt"] = datetime.fromtimestamp(captured_at.timestamp()).isoformat()
    events_data.append({"id": event_doc.id, **event})

print(f"Found {len(events_data)} events")

# Export EMA responses
ema_data = []
try:
    ema_ref = participant_ref.collection("ema_responses")
    for ema_doc in ema_ref.stream():
        ema = ema_doc.to_dict()
        completed_at = ema.get("completedAt")
        if completed_at and hasattr(completed_at, 'timestamp'):
            ema["completedAt"] = datetime.fromtimestamp(completed_at.timestamp()).isoformat()
        ema_data.append({"id": ema_doc.id, **ema})
except Exception as e:
    print(f"Note: No EMA responses found")

print(f"Found {len(ema_data)} EMA responses")

# Export safety alerts
alerts_data = []
try:
    alerts_ref = participant_ref.collection("safety_alerts")
    for alert_doc in alerts_ref.stream():
        alert = alert_doc.to_dict()
        triggered_at = alert.get("triggeredAt")
        if triggered_at and hasattr(triggered_at, 'timestamp'):
            alert["triggeredAt"] = datetime.fromtimestamp(triggered_at.timestamp()).isoformat()
        alerts_data.append({"id": alert_doc.id, **alert})
except Exception as e:
    print(f"Note: No safety alerts found")

print(f"Found {len(alerts_data)} safety alerts")

# Create timestamp for filename
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# Export to files
if "$FORMAT" == "json":
    export_data = {
        "participant": {"id": participant_id, **participant_data},
        "events": events_data,
        "ema_responses": ema_data,
        "safety_alerts": alerts_data,
        "exported_at": datetime.now().isoformat(),
    }

    output_file = output_dir / f"socialscope_export_{participant_id}_{timestamp}.json"
    with open(output_file, "w") as f:
        json.dump(export_data, f, indent=2, default=str)

    print(f"\nExported to: {output_file}")

elif "$FORMAT" == "csv":
    import csv

    # Export events as CSV
    events_file = output_dir / f"socialscope_events_{participant_id}_{timestamp}.csv"
    if events_data:
        with open(events_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=events_data[0].keys())
            writer.writeheader()
            for event in events_data:
                # Flatten nested dicts
                flat_event = {}
                for k, v in event.items():
                    if isinstance(v, dict):
                        flat_event[k] = json.dumps(v)
                    else:
                        flat_event[k] = v
                writer.writerow(flat_event)
        print(f"Events exported to: {events_file}")

    # Export EMA as CSV
    ema_file = output_dir / f"socialscope_ema_{participant_id}_{timestamp}.csv"
    if ema_data:
        with open(ema_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ema_data[0].keys())
            writer.writeheader()
            for ema in ema_data:
                flat_ema = {}
                for k, v in ema.items():
                    if isinstance(v, dict):
                        flat_ema[k] = json.dumps(v)
                    else:
                        flat_ema[k] = v
                writer.writerow(flat_ema)
        print(f"EMA responses exported to: {ema_file}")

print("\nExport complete!")
PYTHON_SCRIPT

else
    # Use the API for export
    echo "Exporting via API..."

    QUERY="participant_id=$PARTICIPANT_ID"
    [ -n "$START_DATE" ] && QUERY="$QUERY&start_date=$START_DATE"
    [ -n "$END_DATE" ] && QUERY="$QUERY&end_date=$END_DATE"

    RESPONSE=$(curl -s "$API_URL/api/export?$QUERY")

    if echo "$RESPONSE" | grep -q "download_url"; then
        DOWNLOAD_URL=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['download_url'])")
        FILENAME=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['filename'])")

        echo "Downloading export..."
        curl -s "$API_URL$DOWNLOAD_URL" -o "$OUTPUT_DIR/$FILENAME"

        echo -e "${GREEN}Export saved to: $OUTPUT_DIR/$FILENAME${NC}"
    else
        echo -e "${RED}Export failed: $RESPONSE${NC}"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}Export complete!${NC}"
