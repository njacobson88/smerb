# REDCap <-> SocialScope App ID Integration Plan

## Overview
Automate participant ID generation so that when a participant completes their
REDCap screening/baseline, a random 9-digit app ID is generated, written to
both Firestore and REDCap, and displayed to the participant for app enrollment.

## Current System
- `valid_participants` Firestore collection holds pre-registered IDs
- App validates entered 9-digit ID against this collection
- IDs are currently created manually via seed scripts

## New Flow

```
Participant completes REDCap baseline
        |
        v
REDCap Data Entry Trigger fires
        |
        v
POST to: https://socialscope-dashboard-api-436153481478.us-central1.run.app/api/redcap/generate-participant-id
        |
        v
Backend endpoint:
  1. Verifies the trigger payload (instrument name, record_id, completion status)
  2. Only fires on the designated "ready" instrument/field (TBD - waiting on research coordinator)
  3. Checks if this record_id already has an app ID (idempotent)
  4. Generates a random 9-digit ID, confirms uniqueness in Firestore
  5. Creates document in valid_participants/{generated_id} with:
     - redcap_record_id: the REDCap record_id
     - created_at: timestamp
     - created_by: "redcap_trigger"
     - inUse: false
  6. Creates mapping in redcap_mappings/{redcap_record_id} with:
     - app_participant_id: the generated 9-digit ID
     - created_at: timestamp
  7. Writes the generated ID back to REDCap via API:
     POST to REDCap API with content=record, writing to a new field
     called `socialscope_app_id` on the participant's record
  8. Returns success response
```

## TODO Items

### REDCap Side (research coordinator)
- [ ] Add a new field `socialscope_app_id` (text field, read-only/calculated)
      to an appropriate instrument - this will display the generated app ID
- [ ] Identify which instrument + field indicates "ready for app"
      (e.g., a specific form marked complete, or a checkbox)
- [ ] Set the Data Entry Trigger URL to:
      `https://socialscope-dashboard-api-436153481478.us-central1.run.app/api/redcap/data-entry-trigger`

### Backend Side (implementation)
- [ ] Add REDCAP_API_TOKEN and REDCAP_API_URL to Cloud Run secrets/env vars
- [ ] Create endpoint: POST /api/redcap/data-entry-trigger
      - Receives REDCap DET payload (record, instrument, project_id, etc.)
      - Filters to only act on the designated trigger instrument
      - Calls the ID generation logic
- [ ] Create endpoint: POST /api/redcap/generate-participant-id
      - Can also be called manually from the dashboard admin UI
      - Generates random 9-digit ID
      - Writes to Firestore valid_participants collection
      - Writes to Firestore redcap_mappings collection
      - Writes back to REDCap via API
- [ ] Add REDCap data pull endpoints for dashboard:
      - GET /api/redcap/participant/{app_id}/surveys
      - Returns PHQ-9, GAD-7, C-SSRS scores etc.

### Dashboard Frontend (future)
- [ ] Show REDCap survey scores on participant detail screen
- [ ] Admin UI to manually trigger ID generation if needed
- [ ] Show REDCap record linkage status

## REDCap Data Entry Trigger Payload Format
When REDCap fires the trigger, it sends a POST with these fields:
- `project_id` - REDCap project ID
- `instrument` - name of the form that was saved
- `record` - the record_id (e.g., "1", "P001")
- `redcap_event_name` - event name in longitudinal projects
- `redcap_data_access_group` - DAG if applicable
- `[instrument]_complete` - completion status (0=incomplete, 1=unverified, 2=complete)
- `redcap_url` - the REDCap base URL

## Security Considerations
- The DET endpoint should verify the request comes from REDCap
  (check project_id matches, optionally verify source IP)
- REDCAP_API_TOKEN must be stored as a Cloud Run secret, not in code
- The endpoint should be idempotent (calling twice for same record = same ID)
- Rate limit the endpoint to prevent abuse

## Firestore Collections

### valid_participants/{9-digit-id} (existing, extended)
```json
{
  "redcap_record_id": "1",
  "created_at": "2026-03-20T...",
  "created_by": "redcap_trigger",
  "inUse": false
}
```

### redcap_mappings/{redcap_record_id} (new)
```json
{
  "app_participant_id": "847293016",
  "created_at": "2026-03-20T...",
  "redcap_event": "consent_and_screen_arm_1"
}
```
