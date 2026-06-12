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

# Load REDCap (and other) secrets from dashboard/backend/.env if present, so a
# deploy from a shell that didn't export them doesn't blank them.
if [[ -f "$(dirname "$0")/../dashboard/backend/.env" ]]; then
  set -a; . "$(dirname "$0")/../dashboard/backend/.env"; set +a
fi

# Guard: REDCAP_API_TOKEN being empty here would silently break ID
# autogeneration (the recurring bug). Abort rather than deploy a blank.
if [[ -z "$REDCAP_API_TOKEN" || -z "$REDCAP_API_URL" ]]; then
  echo "ERROR: REDCAP_API_URL / REDCAP_API_TOKEN are not set. Refusing to deploy"
  echo "       (would blank them and break REDCap ID autogeneration)."
  echo "       Set them in dashboard/backend/.env or export them, then retry."
  exit 1
fi

# IMPORTANT: --update-env-vars (NOT --set-env-vars). --set REPLACES the entire
# env set, which would drop FIREBASE_SERVICE_ACCOUNT_KEY / TWILIO_* / etc. and
# break the service. --update only adds/overwrites the listed keys.
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region=us-central1 \
  --project=r01-redditx-suicide \
  --allow-unauthenticated \
  --no-cpu-throttling \
  --min-instances=1 \
  --update-env-vars="ENVIRONMENT=$ENVIRONMENT,REDCAP_API_URL=$REDCAP_API_URL,REDCAP_API_TOKEN=$REDCAP_API_TOKEN,REDCAP_PROJECT_ID=$REDCAP_PROJECT_ID"

# NOTE: --no-cpu-throttling + --min-instances=1 are REQUIRED for correctness, not
# just performance: the safety-alert background refresh loop and the fire-and-forget
# Firestore writes spawned from Twilio webhooks (escalation stops, dispositions,
# audit trail) only run reliably when CPU is always allocated and an instance stays
# warm. Without these flags those safety writes can be frozen/lost between requests.

echo ""
echo "Deployed $SERVICE_NAME ($ENVIRONMENT)"
