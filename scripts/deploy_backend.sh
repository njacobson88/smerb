#!/bin/bash
# Deploy the SocialScope dashboard backend to Cloud Run.
# Usage: ./scripts/deploy_backend.sh [dev|prod]
#
# Default is prod. Dev deploys to a separate Cloud Run service.

set -e

ENVIRONMENT=${1:-prod}

if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prod" ]]; then
  echo "Usage: $0 [dev|prod]"
  exit 1
fi

echo "======================================"
echo "Deploying backend: $ENVIRONMENT"
echo "======================================"

cd "$(dirname "$0")/../dashboard/backend"

if [[ "$ENVIRONMENT" == "prod" ]]; then
  SERVICE_NAME="socialscope-dashboard-api"
  echo "WARNING: You are deploying to PRODUCTION."
  read -p "Are you sure? (y/N) " confirm
  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
  fi
else
  SERVICE_NAME="socialscope-dashboard-api-dev"
fi

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region=us-central1 \
  --project=r01-redditx-suicide \
  --allow-unauthenticated \
  --no-cpu-throttling \
  --min-instances=1 \
  --set-env-vars="ENVIRONMENT=$ENVIRONMENT,REDCAP_API_URL=$REDCAP_API_URL,REDCAP_API_TOKEN=$REDCAP_API_TOKEN,REDCAP_PROJECT_ID=$REDCAP_PROJECT_ID"

# NOTE: --no-cpu-throttling + --min-instances=1 are REQUIRED for correctness, not
# just performance: the safety-alert background refresh loop and the fire-and-forget
# Firestore writes spawned from Twilio webhooks (escalation stops, dispositions,
# audit trail) only run reliably when CPU is always allocated and an instance stays
# warm. Without these flags those safety writes can be frozen/lost between requests.

echo ""
echo "Deployed $SERVICE_NAME ($ENVIRONMENT)"
