#!/bin/bash
# Deploy only the backend to Cloud Run

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")/backend"

PROJECT_ID="r01-redditx-suicide"
REGION="us-central1"
SERVICE_NAME="socialscope-dashboard-api"

echo "Deploying backend to Cloud Run..."

cd "$BACKEND_DIR"

gcloud config set project $PROJECT_ID

gcloud run deploy $SERVICE_NAME \
    --source . \
    --region $REGION \
    --platform managed \
    --allow-unauthenticated \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 1 \
    --max-instances 2 \
    --timeout 300
# NOTE: deliberately no --set-env-vars here. That flag REPLACES the service's
# entire environment, which would wipe REDCAP_API_TOKEN, SCHEDULER_SECRET,
# TWILIO_*, MSGRAPH_* and the ENVIRONMENT=prod marker that are configured on
# the service. Use --update-env-vars KEY=VALUE to change a single variable.

BACKEND_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)')
echo ""
echo "Backend deployed to: $BACKEND_URL"
