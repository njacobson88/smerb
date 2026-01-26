# SocialScope Dashboard

A monitoring dashboard for the SocialScope social media research study at Dartmouth College.

## Features

### Three Primary Views

1. **Overall Participant View** - See all participants at a glance with weekly data
   - Daily status grid showing EMAs, Reddit screenshots, Twitter screenshots
   - Crisis flag indicators (highlighted in red)
   - Weekly compliance percentages
   - Click any cell to drill down

2. **Participant Detail View** - Deep dive into a single participant
   - Daily summary table with key metrics
   - Total EMAs complete, Reddit screenshots, Twitter screenshots
   - Crisis day count
   - Safety alerts count
   - One-click data export

3. **Day Detail View** - Granular single-day analysis
   - Hourly activity charts
   - Platform breakdown (Reddit vs Twitter)
   - EMA check-in responses
   - Safety alert details
   - Crisis flag highlighting

### Key Metrics (Prominently Displayed)

- **EMAs Complete** - Primary compliance metric (3 per day expected)
- **Reddit Screenshots** - Social media activity tracking
- **Twitter/X Screenshots** - Social media activity tracking
- **Crisis Flag** - Highlighted when participant indicates "Yes" to crisis questions

### Security

- **IP Whitelist** - Only accessible from Dartmouth network
  - Dartmouth main: 129.170.0.0/16
  - Dartmouth secondary: 132.177.0.0/16
  - VPN: 10.0.0.0/8

### Data Export

- Export all participant data as JSON or ZIP
- Filter by date range
- Includes events, EMA responses, and safety alerts

## Deployment (Production)

The dashboard is deployed to:
- **Frontend**: Firebase Hosting (`https://socialscope-dashboard.web.app`)
- **Backend**: Cloud Run (`https://socialscope-dashboard-api-*.run.app`)

### Prerequisites

1. Install [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
2. Install [Firebase CLI](https://firebase.google.com/docs/cli): `npm install -g firebase-tools`
3. Authenticate: `gcloud auth login` and `firebase login`

### Deploy Everything

```bash
./scripts/deploy.sh
```

This will:
1. Build and deploy the backend to Cloud Run
2. Build the React frontend with the production API URL
3. Deploy the frontend to Firebase Hosting

### Deploy Backend Only

```bash
./scripts/deploy_backend.sh
```

### Deploy Frontend Only

```bash
cd dashboard/frontend
npm run build
cd ../..
firebase deploy --only hosting:dashboard
```

### Estimated Costs

- **Firebase Hosting**: Free tier (10GB/month bandwidth)
- **Cloud Run**: ~$0-5/month for low traffic
  - First 2 million requests/month free
  - min-instances=0 means no cost when idle
  - 512MB memory, 1 CPU per instance

## Local Development

### Backend (FastAPI)

```bash
cd dashboard/backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set Firebase credentials
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"

# Run server
python main.py
```

Backend runs on http://localhost:8080

### Frontend (React)

```bash
cd dashboard/frontend

# Install dependencies
npm install

# Run development server
REACT_APP_LOCAL=true npm start
```

Frontend runs on http://localhost:3000

### Quick Start (Local)

Use the startup script:

```bash
./scripts/start_dashboard.sh
```

## Scripts

### `scripts/start_dashboard.sh`
Starts both backend and frontend servers.

### `scripts/export_participant_data.sh`
Export data for a specific participant.

```bash
./scripts/export_participant_data.sh abc123
./scripts/export_participant_data.sh abc123 --start-date 2024-01-01 --end-date 2024-01-31
./scripts/export_participant_data.sh abc123 --format csv
```

### `scripts/generate_weekly_report.sh`
Generate a text summary report of all participants.

```bash
./scripts/generate_weekly_report.sh
./scripts/generate_weekly_report.sh --start-date 2024-01-01 --end-date 2024-01-07
```

### `scripts/check_crisis_flags.sh`
Quick check for crisis flags and safety alerts.

```bash
./scripts/check_crisis_flags.sh          # Check today
./scripts/check_crisis_flags.sh 2024-01-15  # Check specific date
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /api/participants` | List all participants |
| `GET /api/overall_status?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` | Weekly overview |
| `GET /api/participant/{id}/summary` | Participant details |
| `GET /api/participant/{id}/day/{date}` | Single day details |
| `GET /api/export?participant_id={id}` | Export participant data |
| `GET /api/exports/{export_id}` | Download export file |

## Firebase Structure

```
/participants/{id}
  - enrolledAt
  - deviceModel
  - osVersion

/participants/{id}/events/{eventId}
  - type: "screenshot"
  - platform: "reddit" | "twitter"
  - capturedAt
  - url
  - screenshotUrl
  - ocr: { wordCount, extractedText }

/participants/{id}/ema_responses/{responseId}
  - completedAt
  - responses: { question: answer, ... }

/participants/{id}/safety_alerts/{alertId}
  - triggeredAt
  - handled
  - responses
```

## Development Notes

- Frontend uses React with Tailwind CSS (via CDN)
- Charts powered by Recharts
- Icons from Lucide React
- Backend uses FastAPI with Firebase Admin SDK
- Development mode disables IP whitelist (set DEV_MODE=true in config.py)
