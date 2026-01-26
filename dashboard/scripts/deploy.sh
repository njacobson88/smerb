#!/bin/bash
# SocialScope Dashboard Deployment Script
# Deploys backend to Cloud Run and frontend to Firebase Hosting

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$DASHBOARD_DIR")"
BACKEND_DIR="$DASHBOARD_DIR/backend"
FRONTEND_DIR="$DASHBOARD_DIR/frontend"

# GCP/Firebase settings
PROJECT_ID="r01-redditx-suicide"
REGION="us-central1"
SERVICE_NAME="socialscope-dashboard-api"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   SocialScope Dashboard Deployment        ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Check for required tools
command -v gcloud >/dev/null 2>&1 || { echo -e "${RED}Error: gcloud CLI required${NC}"; exit 1; }
command -v firebase >/dev/null 2>&1 || { echo -e "${RED}Error: Firebase CLI required${NC}"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo -e "${RED}Error: npm required${NC}"; exit 1; }

# Ensure we're using the right project
echo -e "${YELLOW}Setting GCP project to $PROJECT_ID...${NC}"
gcloud config set project $PROJECT_ID

# ============================================
# Deploy Backend to Cloud Run
# ============================================
echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   Deploying Backend to Cloud Run          ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

cd "$BACKEND_DIR"

# Build and deploy using Cloud Build
echo -e "${YELLOW}Building and deploying backend...${NC}"
gcloud run deploy $SERVICE_NAME \
    --source . \
    --region $REGION \
    --platform managed \
    --allow-unauthenticated \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 2 \
    --timeout 60 \
    --set-env-vars "DEV_MODE=false"

# Get the service URL
BACKEND_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)')
echo -e "${GREEN}Backend deployed to: $BACKEND_URL${NC}"

# ============================================
# Build and Deploy Frontend to Firebase Hosting
# ============================================
echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   Building Frontend                       ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

cd "$FRONTEND_DIR"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing npm dependencies...${NC}"
    npm install
fi

# Build with production API URL
echo -e "${YELLOW}Building frontend with API URL: $BACKEND_URL${NC}"
REACT_APP_API_URL=$BACKEND_URL npm run build

echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   Deploying Frontend to Firebase Hosting  ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

cd "$PROJECT_ROOT"

# Deploy to Firebase Hosting
echo -e "${YELLOW}Deploying to Firebase Hosting...${NC}"
firebase deploy --only hosting:dashboard

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}   Deployment Complete!                    ${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "Backend API:  ${BLUE}$BACKEND_URL${NC}"
echo -e "Dashboard:    ${BLUE}https://socialscope-dashboard.web.app${NC}"
echo ""
echo -e "${YELLOW}Note: Dashboard is IP-restricted to Dartmouth network${NC}"
echo ""
