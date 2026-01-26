#!/bin/bash
# SocialScope Dashboard Startup Script
# Starts both the FastAPI backend and React frontend

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$DASHBOARD_DIR/backend"
FRONTEND_DIR="$DASHBOARD_DIR/frontend"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   SocialScope Dashboard Startup Script    ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Check for required environment variables
if [ -z "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo -e "${YELLOW}Warning: GOOGLE_APPLICATION_CREDENTIALS not set${NC}"
    echo "You may need to set this to your Firebase service account key"
    echo ""
fi

# Function to cleanup on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down services...${NC}"
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    echo -e "${GREEN}Cleanup complete${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start backend
echo -e "${GREEN}Starting Backend API server...${NC}"
cd "$BACKEND_DIR"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating Python virtual environment...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Start backend in background
python main.py &
BACKEND_PID=$!
echo -e "${GREEN}Backend started (PID: $BACKEND_PID)${NC}"
echo ""

# Wait for backend to be ready
echo "Waiting for backend to start..."
sleep 3

# Start frontend
echo -e "${GREEN}Starting Frontend development server...${NC}"
cd "$FRONTEND_DIR"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing npm dependencies...${NC}"
    npm install
fi

# Start frontend in background
REACT_APP_LOCAL=true npm start &
FRONTEND_PID=$!
echo -e "${GREEN}Frontend started (PID: $FRONTEND_PID)${NC}"
echo ""

echo -e "${BLUE}============================================${NC}"
echo -e "${GREEN}Dashboard is starting up!${NC}"
echo ""
echo -e "Backend API:  ${BLUE}http://localhost:8080${NC}"
echo -e "Frontend:     ${BLUE}http://localhost:3000${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo -e "${BLUE}============================================${NC}"

# Wait for processes
wait
