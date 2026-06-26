# SocialScope Dashboard Backend
# FastAPI application with Dartmouth IP whitelisting and rate limiting

import os
import json
import uuid
import zipfile
import logging
import re
import asyncio
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from ipaddress import ip_address, ip_network
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, quote

from phone_utils import normalize_phone, phones_match, to_e164
from export_utils import is_valid_export_id
from template_utils import safe_format
from enrollment_auth import (
    generate_enrollment_secret, hash_secret, verify_secret,
    build_enrollment_url, enrollment_sms_text,
    enrollment_email_subject, enrollment_email_html,
)
from graph_email import graph_email_configured, send_graph_email, GRAPH_SENDER
from sms_utils import (
    PARTICIPANT_ERROR_KEYWORDS,
    SMS_DISPOSITION_MAP,
    is_participant_error_reply,
    is_optout,
    is_resubscribe,
    parse_oncall_command,
    describe_sms_status,
)
import content_events as content_events_mod

from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import firebase_admin
from firebase_admin import credentials, firestore

import config

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("socialscope-dashboard")

# Initialize Firebase Admin
if not firebase_admin._apps:
    # Use application default credentials or service account
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    else:
        # On Cloud Run, use default credentials with explicit project
        firebase_admin.initialize_app(options={
            'projectId': config.FIREBASE_PROJECT_ID,
        })

db = firestore.client()

# ----------------------------------------------------------------------------
# Custom-token signing for per-participant enrollment auth.
# The default app on Cloud Run uses ADC (compute SA, no private key), which
# CANNOT sign custom tokens. FIREBASE_SERVICE_ACCOUNT_KEY holds the real SA key
# (already used by compliance_notifications); init a dedicated app from it so
# create_custom_token can sign locally.
# ----------------------------------------------------------------------------
_token_signer_app = None


def _get_token_signer_app():
    global _token_signer_app
    if _token_signer_app is None:
        sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY")
        if not sa_json:
            return None
        try:
            cred = credentials.Certificate(json.loads(sa_json))
            _token_signer_app = firebase_admin.initialize_app(cred, name="token-signer")
        except ValueError:
            _token_signer_app = firebase_admin.get_app("token-signer")
        except Exception as e:
            logger.error(f"Token signer init failed: {e}")
            return None
    return _token_signer_app


def mint_enrollment_token(participant_id: str) -> str:
    """Firebase custom token with uid == participantId (string). The app exchanges
    the enrollment secret for this, then signInWithCustomToken — so every Firebase
    request carries request.auth.uid == participantId for per-participant rules."""
    from firebase_admin import auth as fb_auth
    app = _get_token_signer_app()
    token = fb_auth.create_custom_token(str(participant_id), app=app) if app \
        else fb_auth.create_custom_token(str(participant_id))
    return token.decode("utf-8") if isinstance(token, (bytes, bytearray)) else token


# ============================================================================
# Startup Validation
# ============================================================================

# Warn about missing optional configuration
if not config.SCHEDULER_SECRET:
    logger.warning("SCHEDULER_SECRET not set - scheduler endpoint will reject all requests")

if not config.REDCAP_API_URL or not config.REDCAP_API_TOKEN:
    logger.warning("REDCAP_API_URL/TOKEN not set - REDCap integration will not work")

if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN:
    logger.warning("TWILIO credentials not set - IVR/conference features will not work")

# Initialize Twilio client (if credentials available)
twilio_client = None
if config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN:
    from twilio.rest import Client as TwilioClient
    twilio_client = TwilioClient(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)

if config.DEV_MODE:
    logger.warning("DEV_MODE is enabled - IP whitelist is BYPASSED")

# Log configuration on startup
logger.info(f"Environment: {config.ENVIRONMENT} (prefix: '{config.COLLECTION_PREFIX}')")
logger.info(f"Firebase Project: {config.FIREBASE_PROJECT_ID}")
logger.info(f"CORS Origins: {len(config.get_cors_origins())} origins configured")

# ============================================================================
# Rate Limiting Configuration
# ============================================================================

# Create rate limiter - uses client IP address for identification
limiter = Limiter(key_func=get_remote_address)

# FastAPI app
app = FastAPI(
    title="SocialScope Dashboard API",
    description="Monitoring dashboard for SocialScope social media research study",
    version="1.0.0"
)

# Add rate limiter to app state and register exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS configuration - loaded from config (can be overridden via CORS_ORIGINS env var)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# IP Whitelist Middleware for Dartmouth Network
# ============================================================================

def is_ip_allowed(client_ip: str) -> bool:
    """Check if the client IP is within Dartmouth's allowed ranges."""
    if config.DEV_MODE:
        return True

    try:
        client = ip_address(client_ip)
        for cidr in config.DARTMOUTH_IP_RANGES:
            if client in ip_network(cidr, strict=False):
                return True
        return False
    except ValueError:
        logger.warning(f"Invalid IP address format: {client_ip}")
        return False


@app.middleware("http")
async def dartmouth_ip_whitelist(request: Request, call_next):
    """Middleware to restrict access to Dartmouth IP ranges only."""
    # Allow scheduler and REDCap endpoints to bypass IP check
    # (these use their own authentication mechanisms)
    if request.url.path in (
        "/api/scheduler/refresh-cache",
        "/api/redcap/data-entry-trigger",
        "/api/twilio/call-response",
        "/api/twilio/sms-reply",
        "/api/twilio/hold-music",
        "/api/twilio/join-conference",
        "/api/twilio/conference-events",
        "/api/twilio/incoming-call",
        "/api/config/environment",
        "/api/install/links",
        # Participants enroll from anywhere (not the Dartmouth network); this
        # endpoint authenticates with the high-entropy enrollment secret itself.
        "/api/auth/enrollment-token",
        # Twilio delivery-status callbacks (signature-validated, not IP-bound).
        "/api/twilio/message-status",
    ):
        return await call_next(request)

    # Get client IP (handle proxies)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host

    # Check if IP is allowed
    if not is_ip_allowed(client_ip):
        logger.warning(f"Access denied for IP: {client_ip}")
        return JSONResponse(
            status_code=403,
            content={
                "error": "Access denied",
                "message": "This dashboard is only accessible from the Dartmouth network. "
                          "Please connect to Dartmouth WiFi or VPN.",
                "client_ip": client_ip
            }
        )

    return await call_next(request)


# ============================================================================
# Firebase Authentication with Firestore-based User Management
# ============================================================================

security = HTTPBearer(auto_error=False)

# Collection name for dashboard users
DASHBOARD_USERS_COLLECTION = config.col("dashboard_users")


def get_user_from_firestore(email: str) -> Optional[dict]:
    """Get user from Firestore dashboard_users collection."""
    try:
        user_ref = db.collection(DASHBOARD_USERS_COLLECTION).document(email)
        user_doc = user_ref.get()
        if user_doc.exists:
            return user_doc.to_dict()
        return None
    except Exception as e:
        logger.error(f"Error fetching user from Firestore: {e}")
        return None


def is_user_admin(email: str) -> bool:
    """Check if user has admin role."""
    user = get_user_from_firestore(email)
    return user is not None and user.get("role") == "admin"


async def verify_firebase_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """Verify Firebase ID token and return user info."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")

    token = credentials.credentials
    try:
        from firebase_admin import auth as firebase_auth
        decoded_token = firebase_auth.verify_id_token(token)

        email = decoded_token.get("email", "")

        # Check if user exists in dashboard_users collection
        user_data = get_user_from_firestore(email)
        if not user_data:
            logger.warning(f"Unauthorized access attempt from: {email}")
            raise HTTPException(
                status_code=403,
                detail="Access denied. Your account is not authorized to use this dashboard."
            )

        # Add role info to decoded token
        decoded_token["dashboard_role"] = user_data.get("role", "user")
        return decoded_token
    except HTTPException:
        raise
    except firebase_admin.exceptions.FirebaseError as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


async def verify_admin_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """Verify Firebase ID token and ensure user is admin."""
    user = await verify_firebase_token(credentials)
    if user.get("dashboard_role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )
    return user


# ============================================================================
# Health Check
# ============================================================================

@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/config/environment")
def get_environment():
    """Return current environment. No auth required — used by frontend for dev banner."""
    return {
        "environment": config.ENVIRONMENT,
        "collectionPrefix": config.COLLECTION_PREFIX,
    }


@app.get("/api/install/links")
def get_install_links():
    """Return current download links for the app. No auth required (for participants)."""
    return {
        "ios_url": os.getenv("IOS_DOWNLOAD_URL", ""),
        "android_url": os.getenv("ANDROID_DOWNLOAD_URL", ""),
        "ios_version": os.getenv("IOS_APP_VERSION", "1.0.0"),
        "android_version": os.getenv("ANDROID_APP_VERSION", "1.0.0"),
    }


# ============================================================================
# App Distribution — Participant Device & Distribution Management
# ============================================================================

class DistributionUpdate(BaseModel):
    email: Optional[str] = None
    device_type: Optional[str] = None  # "ios" or "android"
    manual_override: Optional[bool] = False  # If true, don't overwrite from REDCap


@app.get("/api/participant/{participant_id}/distribution")
@limiter.limit("30/minute")
def get_participant_distribution(
    request: Request, participant_id: str, user: dict = Depends(verify_firebase_token)
):
    """Get distribution info for a participant (email, device type, invite status)."""
    try:
        # Check both participants and valid_participants collections
        doc = db.collection(config.col("participants")).document(participant_id).get()
        if not doc.exists:
            doc = db.collection(config.col("valid_participants")).document(participant_id).get()
        if not doc.exists:
            return {"distribution": None}

        data = doc.to_dict()
        # Latest enrollment SMS delivery status (set by the send + Twilio
        # status callback) so the dashboard shows real delivery, not just "sent".
        enroll_sms = data.get("enrollmentSms")
        if isinstance(enroll_sms, dict):
            ts = enroll_sms.get("updatedAt")
            enroll_sms = {
                "status": enroll_sms.get("status"),
                "description": enroll_sms.get("description"),
                "errorCode": enroll_sms.get("errorCode"),
                "updatedAt": ts.isoformat() if hasattr(ts, "isoformat") else ts,
            }
        return {
            "distribution": {
                "email": data.get("distributionEmail"),
                "deviceType": data.get("deviceType"),
                "manualOverride": data.get("deviceTypeManualOverride", False),
                "inviteSentAt": data.get("distributionInviteSentAt").isoformat() if data.get("distributionInviteSentAt") and hasattr(data.get("distributionInviteSentAt"), "isoformat") else data.get("distributionInviteSentAt"),
                "inviteStatus": data.get("distributionInviteStatus"),
                "enrollmentSms": enroll_sms,
            }
        }
    except Exception as e:
        logger.error(f"Failed to get distribution info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/participant/{participant_id}/distribution")
@limiter.limit("20/minute")
def update_participant_distribution(
    request: Request,
    participant_id: str,
    body: DistributionUpdate,
    user: dict = Depends(verify_firebase_token),
):
    """Update distribution email and/or device type for a participant."""
    try:
        # Use participants collection with set/merge — creates doc if it doesn't exist yet
        doc_ref = db.collection(config.col("participants")).document(participant_id)
        updates = {}

        if body.email is not None:
            updates["distributionEmail"] = body.email.strip()
        if body.device_type is not None:
            if body.device_type not in ("ios", "android"):
                raise HTTPException(status_code=400, detail="device_type must be 'ios' or 'android'")
            updates["deviceType"] = body.device_type
            if body.manual_override:
                updates["deviceTypeManualOverride"] = True
        if updates:
            updates["distributionUpdatedAt"] = datetime.utcnow()
            updates["distributionUpdatedBy"] = user.get("email")
            doc_ref.set(updates, merge=True)

        logger.info(f"Distribution updated for {participant_id}: {updates} by {user.get('email')}")
        return {"message": "Distribution info updated", "updates": {k: str(v) for k, v in updates.items()}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/participant/{participant_id}/distribution/send-invite")
@limiter.limit("10/minute")
def send_distribution_invite(
    request: Request,
    participant_id: str,
    body: Optional[DistributionUpdate] = None,
    user: dict = Depends(verify_firebase_token),
):
    """
    Send an app distribution invite to a participant.
    Adds them as a Firebase App Distribution tester and triggers the invite email.

    The dashboard passes the currently-selected email/device type in the body so
    that hitting "Send Invite" persists and uses that selection — coordinators no
    longer have to click "Save" first (a common source of "No device type set"
    confusion). Falls back to whatever is already on the participant doc.
    """
    try:
        doc = db.collection(config.col("participants")).document(participant_id).get()
        if not doc.exists:
            doc = db.collection(config.col("valid_participants")).document(participant_id).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Participant not found in either collection")

        data = doc.to_dict()
        # Prefer the selection sent from the dashboard; fall back to the stored value.
        email = (body.email if body else None) or data.get("distributionEmail")
        device_type = (body.device_type if body else None) or data.get("deviceType")

        if not email:
            raise HTTPException(status_code=400, detail="No distribution email set for this participant")
        if not device_type:
            raise HTTPException(status_code=400, detail="No device type set for this participant. Please confirm iOS or Android first.")
        if device_type not in ("ios", "android"):
            raise HTTPException(status_code=400, detail=f"Invalid device type '{device_type}' (expected 'ios' or 'android').")

        # Persist the selection so the participant doc stays consistent with what
        # was actually sent (and so a later send doesn't need it re-entered).
        persist = {}
        if email != data.get("distributionEmail"):
            persist["distributionEmail"] = email
        if device_type != data.get("deviceType"):
            persist["deviceType"] = device_type
        if persist:
            doc.reference.update(persist)

        # Use Firebase App Distribution REST API (not CLI — CLI isn't available on Cloud Run)
        import google.auth
        import google.auth.transport.requests

        # Get credentials for API calls
        creds, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        access_token = creds.token

        project_number = "436153481478"
        if device_type == "ios":
            app_id = f"1:{project_number}:ios:4d04d2e6257b0f0d9f8687"
        else:
            app_id = f"1:{project_number}:android:cd39924bcf90a0ab9f8687"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Step 1: Add tester to the project
        add_url = f"https://firebaseappdistribution.googleapis.com/v1/projects/{project_number}/testers:batchAdd"
        add_resp = http_requests.post(add_url, headers=headers, json={
            "emails": [email]
        }, timeout=30)

        if add_resp.status_code not in (200, 409):  # 409 = already exists
            logger.error(f"Failed to add tester {email}: {add_resp.status_code} {add_resp.text}")
            raise HTTPException(status_code=500, detail=f"Failed to add tester: {add_resp.text}")

        logger.info(f"Tester {email} added (status: {add_resp.status_code})")

        # Step 2: Add tester to the "testers" group
        group_url = f"https://firebaseappdistribution.googleapis.com/v1/projects/{project_number}/groups/testers"
        # First check if group exists, create if not
        group_check = http_requests.get(group_url, headers=headers, timeout=30)
        if group_check.status_code == 404:
            create_group_url = f"https://firebaseappdistribution.googleapis.com/v1/projects/{project_number}/groups"
            http_requests.post(create_group_url, headers=headers, json={
                "name": f"projects/{project_number}/groups/testers",
                "displayName": "testers",
            }, timeout=30)

        # Add tester to group
        group_add_url = f"{group_url}:batchJoin"
        http_requests.post(group_add_url, headers=headers, json={
            "emails": [email]
        }, timeout=30)

        # Update participant record
        doc_ref = db.collection(config.col("participants")).document(participant_id)
        doc_ref.set({
            "distributionInviteSentAt": datetime.utcnow(),
            "distributionInviteStatus": "sent",
            "distributionInviteSentBy": user.get("email"),
            "distributionInviteDeviceType": device_type,
            "distributionEmail": email,
        }, merge=True)

        logger.info(f"Distribution invite sent to {email} ({device_type}) for {participant_id} by {user.get('email')}")

        return {
            "message": f"Tester {email} added to Firebase App Distribution for {device_type}. "
                       f"They will receive an invite email from Firebase to download the app.",
            "email": email,
            "deviceType": device_type,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send distribution invite: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def require_dev_mode():
    """Dependency that blocks debug endpoints in production."""
    if config.ENVIRONMENT != "dev" and not config.DEV_MODE:
        raise HTTPException(status_code=404, detail="Not found")


@app.get("/api/debug/test-signing", dependencies=[Depends(require_dev_mode)])
def debug_test_signing():
    """Debug endpoint to test signed URL generation."""
    try:
        # Test the signing credentials function
        sa_email, access_token = get_signing_credentials()

        # Try to sign a URL for an existing blob
        bucket = get_storage_bucket()
        blob = bucket.blob("exports/test2/bcab47efac3949edb4d9a08565a6d43a.zip")

        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=1),
            method="GET",
            service_account_email=sa_email,
            access_token=access_token
        )

        return {
            "status": "success",
            "sa_email": sa_email,
            "token_prefix": access_token[:20] + "...",
            "signed_url_prefix": url[:100] + "..."
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }


@app.get("/api/debug/day-test/{participant_id}/{date}", dependencies=[Depends(require_dev_mode)])
def debug_day_test(participant_id: str, date: str):
    """Debug endpoint to test day queries."""
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d")
        next_date = target_date + timedelta(days=1)
        target_date_str = target_date.strftime("%Y-%m-%d")
        next_date_str = next_date.strftime("%Y-%m-%d")

        participant_ref = get_participant_ref(participant_id)

        # First check raw field type
        events_ref = participant_ref.collection("events")
        sample_event = list(events_ref.limit(1).stream())
        raw_timestamp_type = None
        raw_timestamp_value = None
        if sample_event:
            raw_data = sample_event[0].to_dict()
            raw_timestamp = raw_data.get("timestamp")
            raw_timestamp_type = type(raw_timestamp).__name__
            raw_timestamp_value = str(raw_timestamp)[:50] if raw_timestamp else None

        # If timestamp is a string, query with string
        # If timestamp is a Firestore timestamp, query with datetime
        if raw_timestamp_type == "str":
            events_query = events_ref.where(
                "timestamp", ">=", f"{target_date_str}T00:00:00+00:00"
            ).where(
                "timestamp", "<", f"{next_date_str}T00:00:00+00:00"
            )
        else:
            # Firestore timestamp
            events_query = events_ref.where(
                "timestamp", ">=", target_date
            ).where(
                "timestamp", "<", next_date
            )
        events = list(events_query.stream())

        # Check EMA field type
        ema_ref = participant_ref.collection("ema_responses")
        sample_ema = list(ema_ref.limit(1).stream())
        ema_timestamp_type = None
        if sample_ema:
            ema_data = sample_ema[0].to_dict()
            ema_timestamp = ema_data.get("completedAt")
            ema_timestamp_type = type(ema_timestamp).__name__

        if ema_timestamp_type == "str":
            ema_query = ema_ref.where(
                "completedAt", ">=", f"{target_date_str}T00:00:00+00:00"
            ).where(
                "completedAt", "<", f"{next_date_str}T00:00:00+00:00"
            )
        else:
            ema_query = ema_ref.where(
                "completedAt", ">=", target_date
            ).where(
                "completedAt", "<", next_date
            )
        emas = list(ema_query.stream())

        # Safety alerts
        alerts_ref = participant_ref.collection("safety_alerts")
        alerts_query = alerts_ref.where(
            "triggeredAt", ">=", target_date
        ).where(
            "triggeredAt", "<", next_date
        )
        alerts = list(alerts_query.stream())

        return {
            "date": date,
            "events_count": len(events),
            "events_types": [e.to_dict().get("eventType", "unknown") for e in events[:10]],
            "ema_count": len(emas),
            "alerts_count": len(alerts),
            "debug": {
                "raw_timestamp_type": raw_timestamp_type,
                "raw_timestamp_value": raw_timestamp_value,
                "ema_timestamp_type": ema_timestamp_type,
            }
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "type": type(e).__name__, "trace": traceback.format_exc()}


@app.get("/api/debug/participant-data/{participant_id}", dependencies=[Depends(require_dev_mode)])
def debug_participant_data(participant_id: str):
    """Debug endpoint to examine participant's raw data."""
    try:
        participant_ref = get_participant_ref(participant_id)

        # Get events
        events_ref = participant_ref.collection("events")
        events = []
        for doc in events_ref.limit(10).stream():
            event_data = doc.to_dict()
            # Convert timestamps for JSON serialization
            if event_data.get("capturedAt") and hasattr(event_data["capturedAt"], 'isoformat'):
                event_data["capturedAt"] = event_data["capturedAt"].isoformat()
            events.append({"id": doc.id, **event_data})

        # Get safety alerts
        alerts_ref = participant_ref.collection("safety_alerts")
        alerts = []
        for doc in alerts_ref.limit(10).stream():
            alert_data = doc.to_dict()
            if alert_data.get("triggeredAt") and hasattr(alert_data["triggeredAt"], 'isoformat'):
                alert_data["triggeredAt"] = alert_data["triggeredAt"].isoformat()
            alerts.append({"id": doc.id, **alert_data})

        # Get EMA responses
        ema_ref = participant_ref.collection("ema_responses")
        emas = []
        for doc in ema_ref.limit(10).stream():
            ema_data = doc.to_dict()
            if ema_data.get("completedAt") and hasattr(ema_data["completedAt"], 'isoformat'):
                ema_data["completedAt"] = ema_data["completedAt"].isoformat()
            emas.append({"id": doc.id, **ema_data})

        return {
            "participant_id": participant_id,
            "events_count": len(events),
            "events": events,
            "safety_alerts_count": len(alerts),
            "safety_alerts": alerts,
            "ema_responses_count": len(emas),
            "ema_responses": emas,
        }
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@app.get("/api/debug/participants-test", dependencies=[Depends(require_dev_mode)])
def debug_participants_test():
    """Debug endpoint to test participant loading."""
    try:
        # Test with enrolled_only=True (default)
        enrolled_participants = get_all_participant_ids(enrolled_only=True)
        # Test with enrolled_only=False
        all_participants = get_all_participant_ids(enrolled_only=False)

        test2_found = any(p['id'] == 'test2' for p in enrolled_participants)
        return {
            "enrolled_participants": len(enrolled_participants),
            "all_participants": len(all_participants),
            "enrolled_ids": [p['id'] for p in enrolled_participants[:20]],
            "test2_found": test2_found,
            "test2_data": next((p for p in enrolled_participants if p['id'] == 'test2'), None),
        }
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@app.get("/api/debug/collections", dependencies=[Depends(require_dev_mode)])
def debug_collections():
    """Debug endpoint to check Firestore connectivity."""
    try:
        # List all documents in participants collection
        participants_ref = db.collection(config.col("participants"))
        docs = list(participants_ref.limit(10).stream())

        result = {
            "project_id": config.FIREBASE_PROJECT_ID,
            "participants_count": len(docs),
            "participant_ids": [doc.id for doc in docs],
            "sample_data": {}
        }

        # Get sample data from first participant
        if docs:
            first_doc = docs[0]
            data = first_doc.to_dict()
            result["sample_data"] = {
                "id": first_doc.id,
                "fields": list(data.keys()) if data else [],
            }

        # Also try to list root collections
        try:
            collections = [c.id for c in db.collections()]
            result["root_collections"] = collections

            # Check valid_participants collection
            valid_ref = db.collection(config.col("valid_participants"))
            valid_docs = list(valid_ref.limit(10).stream())
            result["valid_participants_count"] = len(valid_docs)
            result["valid_participant_ids"] = [doc.id for doc in valid_docs]
            if valid_docs:
                result["valid_sample"] = {
                    "id": valid_docs[0].id,
                    "data": valid_docs[0].to_dict()
                }
        except Exception as e:
            result["root_collections"] = f"error: {e}"

        # Check for test2 specifically
        test2_ref = db.collection(config.col("participants")).document("test2")
        test2_doc = test2_ref.get()
        result["test2_exists"] = test2_doc.exists
        if test2_doc.exists:
            result["test2_data"] = test2_doc.to_dict()

        # Check if test2 has subcollections
        try:
            test2_events = list(test2_ref.collection("events").limit(5).stream())
            result["test2_events_count"] = len(test2_events)
        except Exception as e:
            result["test2_events_count"] = "error"

        return result
    except Exception as e:
        logger.error(f"Debug error: {e}", exc_info=True)
        return {"error": str(e), "type": type(e).__name__}


# ============================================================================
# Participant Helpers
# ============================================================================

def get_all_participant_ids(enrolled_only: bool = True) -> list:
    """Get participant IDs from both collections.

    Args:
        enrolled_only: If True, only return participants that have enrolled (inUse=True or has enrolledAt)
    """
    seen_ids = set()
    participants_info = []

    # Check both collections
    for collection_name in [config.col("participants"), config.col("valid_participants")]:
        collection_ref = db.collection(collection_name)
        for doc in collection_ref.stream():
            if doc.id in seen_ids:
                continue

            data = doc.to_dict()

            # Filter to only enrolled/registered participants if requested
            if enrolled_only:
                is_enrolled = (
                    data.get("inUse") == True or
                    data.get("enrolledAt") is not None or
                    data.get("lastEnrolledAt") is not None or
                    data.get("enrolledViaRedcap") == True
                )
                if not is_enrolled:
                    continue

            seen_ids.add(doc.id)
            enrolled_at = data.get("enrolledAt") or data.get("lastEnrolledAt")
            participants_info.append({
                "id": doc.id,
                "data": data,
                "enrolledAt": enrolled_at,
            })

    return participants_info


def get_participant_data(participant_id: str) -> Optional[dict]:
    """Get participant data from either collection."""
    # Try participants collection first
    doc = db.collection(config.col("participants")).document(participant_id).get()
    if doc.exists:
        return doc.to_dict()

    # Try valid_participants collection
    doc = db.collection(config.col("valid_participants")).document(participant_id).get()
    if doc.exists:
        return doc.to_dict()

    return None


def get_participant_ref(participant_id: str):
    """
    Get reference for participant's subcollections (events, ema_responses, safety_alerts).
    These are always stored under participants/{id}/ regardless of where the metadata is.
    """
    return db.collection(config.col("participants")).document(participant_id)


# ============================================================================
# Per-participant enrollment auth (DORMANT until the app + rules cut over).
# Nothing here changes current behavior: no participant-creation change, no rule
# enforcement. The send endpoint is coordinator-triggered; the token endpoint is
# only called by the (future) auth-capable app. See docs/per_participant_auth.md.
# ============================================================================

ENROLLMENT_BASE_URL = os.getenv("ENROLLMENT_BASE_URL", "https://socialscope-dashboard.web.app")
# This backend's own public URL — the Twilio delivery status_callback target
# (must be publicly reachable; that callback path is IP-exempt in the middleware).
PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "https://socialscope-dashboard-api-436153481478.us-central1.run.app")


def _store_enrollment_hash(participant_id: str, secret_hash: str):
    """Persist the secret hash on whichever participant record exists. Stored on
    valid_participants (the pre-enrollment authority) when present, and on
    participants/{id} (merge) so the token endpoint can read it either way. The
    hash is one-way over a ~190-bit secret, so storing it is safe."""
    payload = {"enrollmentSecretHash": secret_hash, "enrollmentSecretUpdatedAt": datetime.utcnow()}
    wrote = False
    vp_ref = db.collection(config.col("valid_participants")).document(participant_id)
    if vp_ref.get().exists:
        vp_ref.set(payload, merge=True)
        wrote = True
    # Always also store on participants/{id} (merge creates it if needed — same
    # pattern the distribution endpoint already uses).
    db.collection(config.col("participants")).document(participant_id).set(payload, merge=True)
    return wrote


def _read_enrollment_hash(participant_id: str):
    for col_name in ("participants", "valid_participants"):
        doc = db.collection(config.col(col_name)).document(participant_id).get()
        if doc.exists:
            h = doc.to_dict().get("enrollmentSecretHash")
            if h:
                return h
    return None


@app.post("/api/participant/{participant_id}/enrollment/send")
@limiter.limit("10/minute")
def send_enrollment_link(request: Request, participant_id: str,
                         user: dict = Depends(verify_firebase_token)):
    """Coordinator action: (re)issue the participant's app sign-in link and send
    it via SMS + email. Rotates the secret each send (we store only the hash, so
    a resend necessarily mints a new link and invalidates the prior one)."""
    data = get_participant_data(participant_id)
    if not data:
        raise HTTPException(status_code=404, detail="Participant not found")

    phone = data.get("phone") or data.get("phoneNumber")
    email = data.get("distributionEmail") or data.get("email")
    if not phone and not email:
        raise HTTPException(status_code=400,
                            detail="No phone or distribution email on file for this participant")

    # Rotate + store the secret, build the link.
    secret = generate_enrollment_secret()
    _store_enrollment_hash(participant_id, hash_secret(secret))
    url = build_enrollment_url(ENROLLMENT_BASE_URL, participant_id, secret)

    sent = {"sms": False, "email": False, "errors": []}

    if phone and twilio_client:
        try:
            to = to_e164(phone)
            # Register a delivery status_callback so we learn whether the carrier
            # actually delivered it (vs. just queued). A successful create only
            # means QUEUED — carriers can still filter it (error 30007 on the
            # unverified toll-free number), which is invisible without this.
            status_cb = f"{PUBLIC_API_BASE_URL}/api/twilio/message-status?participantId={quote(str(participant_id))}"
            msg = twilio_client.messages.create(
                body=enrollment_sms_text(url), from_=config.TWILIO_FROM_NUMBER, to=to,
                status_callback=status_cb)
            sent["sms"] = True
            sent["smsSid"] = msg.sid
            # Record the initial (queued) status; the webhook updates it as Twilio
            # reports sent -> delivered/undelivered.
            db.collection(config.col("participants")).document(participant_id).set(
                {"enrollmentSms": {"sid": msg.sid, "status": msg.status or "queued",
                                   "to": to, "updatedAt": datetime.utcnow(),
                                   "description": describe_sms_status(msg.status)}}, merge=True)
            logger.info(f"[Enrollment] SMS queued for {participant_id}: {msg.sid} -> {to}")
        except Exception as e:
            sent["errors"].append(f"sms: {e}")
            logger.error(f"[Enrollment] SMS send failed for {participant_id}: {e}")

    # Email via Microsoft Graph (Mail.Send as the study mailbox).
    if email and graph_email_configured():
        try:
            send_graph_email(email, enrollment_email_subject(), html=enrollment_email_html(url))
            sent["email"] = True
        except Exception as e:
            sent["errors"].append(f"email: {e}")
            logger.error(f"[Enrollment] Graph email failed for {participant_id}: {e}")
    elif email:
        sent["errors"].append("email: no email provider configured")

    # Audit (no secret/URL persisted — the link is a credential).
    try:
        db.collection(config.col("participants")).document(participant_id).set(
            {"enrollmentLinkLastSentAt": datetime.utcnow(),
             "enrollmentLinkLastSentBy": user.get("email")}, merge=True)
    except Exception:
        pass

    logger.info(f"[Enrollment] Link issued for {participant_id} by {user.get('email')} "
                f"(sms={sent['sms']}, email={sent['email']})")
    return {"participantId": participant_id, "sent": sent,
            "hasPhone": bool(phone), "hasEmail": bool(email)}


@app.post("/api/auth/enrollment-token")
@limiter.limit("20/minute")
async def enrollment_token(request: Request):
    """Public (IP-exempt): the app exchanges {participantId, secret} for a
    Firebase custom token. Authenticated by the high-entropy secret itself."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")
    participant_id = str(body.get("participantId") or "").strip()
    secret = body.get("secret")
    if not participant_id or not secret:
        raise HTTPException(status_code=400, detail="participantId and secret required")

    stored_hash = _read_enrollment_hash(participant_id)
    if not stored_hash or not verify_secret(secret, stored_hash):
        # Same generic error whether the participant or the secret is wrong.
        raise HTTPException(status_code=401, detail="Invalid enrollment link")

    try:
        token = mint_enrollment_token(participant_id)
    except Exception as e:
        logger.error(f"[Enrollment] Token mint failed for {participant_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not issue token")

    logger.info(f"[Enrollment] Token issued for {participant_id}")
    return {"token": token, "participantId": participant_id}


@app.post("/api/twilio/message-status")
async def twilio_message_status(request: Request):
    """Twilio delivery status callback for enrollment SMS. Twilio POSTs here as
    the message moves queued -> sent -> delivered/undelivered/failed. We record
    the latest status on the participant doc so the dashboard shows real delivery
    (vs. the misleading 'queued = sent'). Signature-validated; IP-exempt."""
    if not await _twilio_webhook_is_valid(request):
        return _twilio_forbidden()
    try:
        form = await request.form()
    except Exception:
        return Response(status_code=204)
    sid = form.get("MessageSid") or form.get("SmsSid")
    status = form.get("MessageStatus") or form.get("SmsStatus")
    error_code = form.get("ErrorCode") or None
    to = form.get("To")
    participant_id = request.query_params.get("participantId")

    logger.info(f"[MsgStatus] {sid} -> {status} (err={error_code}) pid={participant_id}")
    if participant_id:
        try:
            db.collection(config.col("participants")).document(participant_id).set(
                {"enrollmentSms": {
                    "sid": sid, "status": status, "errorCode": error_code, "to": to,
                    "description": describe_sms_status(status, error_code),
                    "updatedAt": datetime.utcnow(),
                }}, merge=True)
        except Exception as e:
            logger.error(f"[MsgStatus] failed to record for {participant_id}: {e}")
    return Response(status_code=204)


# ============================================================================
# Dashboard Cache for Scalability
# ============================================================================

DASHBOARD_CACHE_COLLECTION = config.col("dashboard_cache")

# ============================================================================
# Safety Alerts In-Memory Cache (refreshed every 2 minutes)
# ============================================================================

SAFETY_ALERT_CACHE: Dict[str, Any] = {
    "alerts": [],
    "updated_at": None,
    "status": "never_run",
    "error": None,
}
_safety_alert_lock = asyncio.Lock()
_safety_alert_stop_event = asyncio.Event()
_safety_alert_task = None
SAFETY_ALERT_REFRESH_SECONDS = 120  # 2 minutes


def _safe_get_responses(data: dict, key: str = "responses") -> dict:
    """Safely extract responses dict, handling JSON string format."""
    resp = data.get(key, {})
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except (json.JSONDecodeError, TypeError, ValueError):
            resp = {}
    return resp if isinstance(resp, dict) else {}


def fetch_live_safety_alerts() -> List[Dict[str, Any]]:
    """
    Fetch safety alerts directly from Firestore.
    This is the core logic extracted for reuse by both the background
    refresh loop and the manual refresh endpoint.
    """
    alerts = []

    # Get all enrolled participants
    participants_info = get_all_participant_ids(enrolled_only=True)

    for p_info in participants_info:
        pid = p_info["id"]
        participant_ref = get_participant_ref(pid)

        try:
            # Fetch safety alerts
            alerts_ref = participant_ref.collection("safety_alerts")
            alert_docs = list(alerts_ref.order_by("triggeredAt", direction=firestore.Query.DESCENDING).limit(50).stream())

            # Fetch recent EMA responses to match with alerts
            ema_ref = participant_ref.collection("ema_responses")
            ema_docs = list(ema_ref.order_by("completedAt", direction=firestore.Query.DESCENDING).limit(100).stream())

            # Index EMAs by sessionId for matching
            ema_by_session = {}
            for ema_doc in ema_docs:
                ema = ema_doc.to_dict()
                session_id = ema.get("sessionId")
                if session_id:
                    ema_by_session[session_id] = _safe_get_responses(ema)

            for alert_doc in alert_docs:
                try:
                    alert = alert_doc.to_dict()
                    triggered_at = alert.get("triggeredAt")

                    if not triggered_at:
                        continue

                    # Format timestamp
                    if hasattr(triggered_at, 'timestamp'):
                        alert_datetime = datetime.fromtimestamp(triggered_at.timestamp())
                        alert_date = alert_datetime.strftime("%Y-%m-%d")
                        alert_time = alert_datetime.strftime("%H:%M:%S")
                        triggered_iso = alert_datetime.isoformat() + "Z"
                    else:
                        alert_date = triggered_at.strftime("%Y-%m-%d")
                        alert_time = triggered_at.strftime("%H:%M:%S")
                        triggered_iso = triggered_at.isoformat() + "Z"

                    # Get alert responses and merge with full EMA data
                    alert_responses = _safe_get_responses(alert)
                    session_id = alert.get("sessionId")

                    # Try to get full EMA responses for this session
                    full_responses = ema_by_session.get(session_id, {})
                    merged_responses = {**alert_responses, **full_responses}

                    # Pull disposition status from the matching safety_events doc
                    # so EVERY researcher sees that an alert is already handled
                    # (and by whom) — not just the one who logged it. Without this
                    # two researchers can double-act on the same crisis.
                    handled_status = {}
                    try:
                        se_doc = db.collection(SAFETY_EVENTS_COLLECTION).document(alert_doc.id).get()
                        if se_doc.exists:
                            se = se_doc.to_dict()
                            lr = se.get("lastRespondedAt")
                            if lr and hasattr(lr, "timestamp"):
                                lr = datetime.fromtimestamp(lr.timestamp()).isoformat()
                            handled_status = {
                                "escalationStopped": se.get("escalationStopped", False),
                                "currentDisposition": se.get("currentDisposition"),
                                "acknowledged": se.get("acknowledged", False),
                                "lastRespondedBy": se.get("lastRespondedBy") or se.get("acknowledgedBy"),
                                "lastRespondedAt": lr,
                            }
                    except Exception:
                        pass

                    alerts.append({
                        "participantId": pid,
                        "alertId": alert_doc.id,
                        **handled_status,
                        "date": alert_date,
                        "time": alert_time,
                        "triggeredAt": triggered_iso,
                        "sessionId": session_id,
                        # crisis_indicated drives the dashboard's red CRISIS badge —
                        # true for a participant-confirmed danger alert.
                        "crisis_indicated": alert.get("confirmedDanger") is True,
                        "count": 1,  # one row per alert (alerts are not grouped)
                        "triggerReason": alert.get("triggerReason"),
                        "responses": merged_responses,
                        "notificationSent": alert.get("notificationSent", False),
                        # New confirmation-based alert fields
                        "handled": alert.get("handled", False),
                        "confirmedDanger": alert.get("confirmedDanger"),
                        "confirmationNumber": alert.get("confirmationNumber"),
                        "triggerQuestion": alert.get("triggerQuestion"),
                        # Notification results
                        "slackResult": alert.get("slackResult"),
                        "smsResults": alert.get("smsResults"),
                    })
                except Exception as alert_err:
                    logger.warning(f"Error processing alert {alert_doc.id} for {pid}: {alert_err}")
                    continue

        except Exception as e:
            logger.warning(f"Error fetching alerts for {pid}: {e}")
            continue

    # Sort by triggeredAt descending (most recent first)
    alerts.sort(key=lambda x: x.get("triggeredAt", ""), reverse=True)
    return alerts


def _persist_safety_alerts_to_firestore(alerts):
    """Write safety alerts cache to Firestore for fast cold-start reads."""
    try:
        cache_data = {
            "alerts": alerts,
            "updatedAt": datetime.utcnow(),
            "alertCount": len(alerts),
        }
        db.collection(DASHBOARD_CACHE_COLLECTION).document("safety_alerts").set(cache_data)
    except Exception as e:
        logger.warning(f"[SafetyAlerts] Failed to persist to Firestore cache: {e}")


def _load_safety_alerts_from_firestore():
    """Load safety alerts from Firestore cache (for cold starts)."""
    try:
        doc = db.collection(DASHBOARD_CACHE_COLLECTION).document("safety_alerts").get()
        if doc.exists:
            data = doc.to_dict()
            updated_at = data.get("updatedAt")
            if updated_at and hasattr(updated_at, "timestamp"):
                updated_at = datetime.fromtimestamp(updated_at.timestamp())
            return {
                "alerts": data.get("alerts", []),
                "updated_at": updated_at.isoformat() + "Z" if updated_at else None,
                "status": "ok",
                "error": None,
            }
    except Exception as e:
        logger.warning(f"[SafetyAlerts] Failed to load from Firestore cache: {e}")
    return None


async def refresh_safety_alert_cache():
    """Background task that refreshes the safety alert cache every 2 minutes."""
    global SAFETY_ALERT_CACHE
    logger.info("[SafetyAlerts] Background refresh loop starting")

    # On startup, try to load from Firestore cache first (fast cold start)
    cached = await asyncio.get_event_loop().run_in_executor(None, _load_safety_alerts_from_firestore)
    if cached:
        async with _safety_alert_lock:
            SAFETY_ALERT_CACHE.update(cached)
        logger.info(f"[SafetyAlerts] Loaded {len(cached['alerts'])} alerts from Firestore cache (cold start)")

    while not _safety_alert_stop_event.is_set():
        try:
            # Run the blocking Firestore call in a thread pool
            loop = asyncio.get_event_loop()
            alerts = await loop.run_in_executor(None, fetch_live_safety_alerts)

            async with _safety_alert_lock:
                SAFETY_ALERT_CACHE.update({
                    "alerts": alerts,
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                    "status": "ok",
                    "error": None,
                })

            # Persist to Firestore so next cold start is fast
            await loop.run_in_executor(None, _persist_safety_alerts_to_firestore, alerts)

            logger.info(f"[SafetyAlerts] Cache refreshed: {len(alerts)} alerts")

        except Exception as exc:
            logger.exception("[SafetyAlerts] Refresh failed")
            async with _safety_alert_lock:
                SAFETY_ALERT_CACHE.update({
                    "status": "error",
                    "error": str(exc),
                })

        # Wait for the refresh interval or stop event
        try:
            await asyncio.wait_for(
                _safety_alert_stop_event.wait(),
                timeout=SAFETY_ALERT_REFRESH_SECONDS
            )
            # If we get here without timeout, stop event was set
            break
        except asyncio.TimeoutError:
            # Normal timeout, continue the loop
            pass

    logger.info("[SafetyAlerts] Background refresh loop stopped")


@app.on_event("startup")
async def start_safety_alert_refresh():
    """Start the background safety alert refresh task on app startup."""
    global _safety_alert_task
    _safety_alert_stop_event.clear()
    _safety_alert_task = asyncio.create_task(refresh_safety_alert_cache())
    logger.info("[SafetyAlerts] Background refresh task started")


@app.on_event("shutdown")
async def stop_safety_alert_refresh():
    """Stop the background safety alert refresh task on app shutdown."""
    global _safety_alert_task
    if _safety_alert_task:
        _safety_alert_stop_event.set()
        try:
            await asyncio.wait_for(_safety_alert_task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("[SafetyAlerts] Refresh task did not stop gracefully")
        _safety_alert_task = None
    logger.info("[SafetyAlerts] Background refresh task stopped")


def compute_participant_stats(participant_id: str, start_dt: datetime, end_dt: datetime) -> dict:
    """Compute daily stats for a single participant within date range."""
    participant_ref = get_participant_ref(participant_id)
    events_ref = participant_ref.collection("events")

    # Query events within date range
    events_query = events_ref.where(
        "timestamp", ">=", start_dt
    ).where(
        "timestamp", "<", end_dt + timedelta(days=1)
    )

    events = list(events_query.stream())

    # Aggregate by day
    daily_status = defaultdict(lambda: {
        "screenshots": 0,
        "ocr_chars": 0,
        "checkins": 0,
        "safety_alerts": 0,
        "reddit": 0,
        "twitter": 0,
        "crisis_indicated": False,
    })

    for event_doc in events:
        event = event_doc.to_dict()
        captured_at = event.get("timestamp") or event.get("createdAt")
        if not captured_at:
            continue

        if hasattr(captured_at, 'timestamp'):
            event_date = datetime.fromtimestamp(captured_at.timestamp()).strftime("%Y-%m-%d")
        elif isinstance(captured_at, str):
            event_date = captured_at[:10]
        else:
            event_date = captured_at.strftime("%Y-%m-%d")

        event_type = event.get("eventType", event.get("type", ""))

        if event_type == "screenshot":
            daily_status[event_date]["screenshots"] += 1
            ocr = event.get("ocr", {})
            if ocr:
                daily_status[event_date]["ocr_chars"] += ocr.get("wordCount", 0) * 5

            platform = event.get("platform", "").lower()
            if platform == "reddit":
                daily_status[event_date]["reddit"] += 1
            elif platform in ("twitter", "x"):
                daily_status[event_date]["twitter"] += 1
        elif event_type == "checkin":
            daily_status[event_date]["checkins"] += 1

    # Get safety alerts
    try:
        alerts_ref = participant_ref.collection("safety_alerts")
        alerts_query = alerts_ref.where(
            "triggeredAt", ">=", start_dt
        ).where(
            "triggeredAt", "<=", end_dt + timedelta(days=1)
        )

        for alert_doc in alerts_query.stream():
            alert = alert_doc.to_dict()
            triggered_at = alert.get("triggeredAt")
            if triggered_at:
                if hasattr(triggered_at, 'timestamp'):
                    alert_date = datetime.fromtimestamp(triggered_at.timestamp()).strftime("%Y-%m-%d")
                else:
                    alert_date = triggered_at.strftime("%Y-%m-%d")
                daily_status[alert_date]["safety_alerts"] += 1
    except Exception as e:
        logger.debug(f"Silently handled exception: {e}")

    # Get check-ins from ema_responses
    try:
        checkins_ref = participant_ref.collection("ema_responses")
        checkins_query = checkins_ref.where(
            "completedAt", ">=", start_dt
        ).where(
            "completedAt", "<", end_dt + timedelta(days=1)
        )

        for checkin_doc in checkins_query.stream():
            checkin = checkin_doc.to_dict()
            completed_at = checkin.get("completedAt")
            if completed_at:
                if hasattr(completed_at, 'timestamp'):
                    checkin_date = datetime.fromtimestamp(completed_at.timestamp()).strftime("%Y-%m-%d")
                elif isinstance(completed_at, str):
                    checkin_date = completed_at[:10]
                else:
                    checkin_date = completed_at.strftime("%Y-%m-%d")
                daily_status[checkin_date]["checkins"] += 1

                # Check for crisis indicator
                responses = checkin.get("responses", {})
                if isinstance(responses, str):
                    try:
                        responses = json.loads(responses)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        responses = {}

                for key, value in responses.items():
                    if isinstance(value, str) and value.lower() in ("yes", "true"):
                        if "crisis" in key.lower() or "harm" in key.lower() or "hurt" in key.lower():
                            daily_status[checkin_date]["crisis_indicated"] = True
    except Exception as e:
        logger.debug(f"Silently handled exception: {e}")

    return dict(daily_status)


@app.post("/api/admin/refresh-cache")
@limiter.limit("5/minute")
def refresh_dashboard_cache(request: Request, user: dict = Depends(verify_admin_token)):
    """
    Refresh the dashboard cache with pre-computed participant stats.
    This endpoint should be called by Cloud Scheduler every hour.
    """
    try:
        # Calculate date range (last 14 days)
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=14)

        # Get all enrolled participants
        participants_info = get_all_participant_ids(enrolled_only=True)

        cached_data = []
        for p_info in participants_info:
            pid = p_info["id"]
            participant_data = p_info["data"]
            enrolled_at = p_info["enrolledAt"]

            if enrolled_at:
                if hasattr(enrolled_at, 'timestamp'):
                    study_start = datetime.fromtimestamp(enrolled_at.timestamp())
                else:
                    study_start = enrolled_at
            else:
                study_start = start_dt

            # Compute stats for this participant
            daily_status = compute_participant_stats(pid, start_dt, end_dt)

            # Calculate totals
            total_screenshots = sum(d["screenshots"] for d in daily_status.values())
            total_checkins = sum(d["checkins"] for d in daily_status.values())
            total_reddit = sum(d["reddit"] for d in daily_status.values())
            total_twitter = sum(d["twitter"] for d in daily_status.values())
            days_count = max(1, len(daily_status))

            # Build daily status list
            daily_list = []
            current = start_dt
            while current <= end_dt:
                date_str = current.strftime("%Y-%m-%d")
                day_data = daily_status.get(date_str, {
                    "screenshots": 0, "ocr_chars": 0, "checkins": 0, "safety_alerts": 0,
                    "reddit": 0, "twitter": 0, "crisis_indicated": False
                })
                daily_list.append({
                    "date": date_str,
                    **day_data
                })
                current += timedelta(days=1)

            cached_data.append({
                "id": pid,
                "study_start_date": study_start.strftime("%Y-%m-%d") if study_start else None,
                "dailyStatus": daily_list,
                "weeklyScreenshots": total_screenshots,
                "weeklyCheckins": total_checkins,
                "weeklyReddit": total_reddit,
                "weeklyTwitter": total_twitter,
                "overallCompliance": min(100, int((total_checkins / (days_count * config.EMA_PROMPTS_PER_DAY)) * 100)) if days_count > 0 else 0,
                # Surfaces a dashboard warning when a device's local capture is
                # paused on a full cache (data-loss risk; usually a long offline gap).
                "captureDiskPaused": (p_info.get("data") or {}).get("captureDiskPaused", False),
            })

        # Store in Firestore cache
        cache_ref = db.collection(DASHBOARD_CACHE_COLLECTION).document("overall_status")
        cache_ref.set({
            "participants": cached_data,
            "refreshedAt": datetime.utcnow(),
            "startDate": start_dt.strftime("%Y-%m-%d"),
            "endDate": end_dt.strftime("%Y-%m-%d"),
            "participantCount": len(cached_data),
        })

        logger.info(f"Dashboard cache refreshed: {len(cached_data)} participants")
        return {
            "message": "Cache refreshed successfully",
            "participantCount": len(cached_data),
            "refreshedAt": datetime.utcnow().isoformat() + "Z",
        }

    except Exception as e:
        logger.error(f"Failed to refresh cache: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cache/status")
@limiter.limit("60/minute")
def get_cache_status(request: Request, user: dict = Depends(verify_firebase_token)):
    """Get the current cache status and last refresh time."""
    try:
        cache_ref = db.collection(DASHBOARD_CACHE_COLLECTION).document("overall_status")
        cache_doc = cache_ref.get()

        if not cache_doc.exists:
            return {
                "cached": False,
                "message": "Cache not initialized. An admin needs to refresh the cache.",
            }

        data = cache_doc.to_dict()
        refreshed_at = data.get("refreshedAt")

        if refreshed_at and hasattr(refreshed_at, 'timestamp'):
            refreshed_at = datetime.fromtimestamp(refreshed_at.timestamp())

        return {
            "cached": True,
            "refreshedAt": (refreshed_at.isoformat() + "Z") if refreshed_at else None,
            "participantCount": data.get("participantCount", 0),
            "startDate": data.get("startDate"),
            "endDate": data.get("endDate"),
        }
    except Exception as e:
        logger.error(f"Failed to get cache status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/refresh-cache")
def scheduler_refresh_cache(secret: str = Query(..., description="Scheduler secret key")):
    """
    Refresh cache endpoint for Cloud Scheduler.
    Authenticated via secret key instead of Firebase token.
    Called automatically every hour by Cloud Scheduler.
    """
    # Verify secret key
    if secret != config.SCHEDULER_SECRET:
        logger.warning(f"Invalid scheduler secret attempted")
        raise HTTPException(status_code=403, detail="Invalid secret")

    try:
        # Calculate date range (last 14 days)
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=14)

        # Get all enrolled participants
        participants_info = get_all_participant_ids(enrolled_only=True)

        cached_data = []
        for p_info in participants_info:
            pid = p_info["id"]
            enrolled_at = p_info["enrolledAt"]

            if enrolled_at:
                if hasattr(enrolled_at, 'timestamp'):
                    study_start = datetime.fromtimestamp(enrolled_at.timestamp())
                else:
                    study_start = enrolled_at
            else:
                study_start = start_dt

            # Compute stats for this participant
            daily_status = compute_participant_stats(pid, start_dt, end_dt)

            # Calculate totals
            total_screenshots = sum(d.get("screenshots", 0) for d in daily_status.values())
            total_checkins = sum(d.get("checkins", 0) for d in daily_status.values())
            total_reddit = sum(d.get("reddit", 0) for d in daily_status.values())
            total_twitter = sum(d.get("twitter", 0) for d in daily_status.values())
            days_count = max(1, len(daily_status))

            # Build daily status list
            daily_list = []
            current = start_dt
            while current <= end_dt:
                date_str = current.strftime("%Y-%m-%d")
                day_data = daily_status.get(date_str, {
                    "screenshots": 0, "ocr_chars": 0, "checkins": 0, "safety_alerts": 0,
                    "reddit": 0, "twitter": 0, "crisis_indicated": False
                })
                daily_list.append({"date": date_str, **day_data})
                current += timedelta(days=1)

            cached_data.append({
                "id": pid,
                "study_start_date": study_start.strftime("%Y-%m-%d") if study_start else None,
                "dailyStatus": daily_list,
                "weeklyScreenshots": total_screenshots,
                "weeklyCheckins": total_checkins,
                "weeklyReddit": total_reddit,
                "weeklyTwitter": total_twitter,
                "overallCompliance": min(100, int((total_checkins / (days_count * config.EMA_PROMPTS_PER_DAY)) * 100)) if days_count > 0 else 0,
                # Surfaces a dashboard warning when a device's local capture is
                # paused on a full cache (data-loss risk; usually a long offline gap).
                "captureDiskPaused": (p_info.get("data") or {}).get("captureDiskPaused", False),
            })

        # Store in Firestore cache
        cache_ref = db.collection(DASHBOARD_CACHE_COLLECTION).document("overall_status")
        cache_ref.set({
            "participants": cached_data,
            "refreshedAt": datetime.utcnow(),
            "startDate": start_dt.strftime("%Y-%m-%d"),
            "endDate": end_dt.strftime("%Y-%m-%d"),
            "participantCount": len(cached_data),
        })

        logger.info(f"[Scheduler] Dashboard cache refreshed: {len(cached_data)} participants")
        return {
            "message": "Cache refreshed successfully by scheduler",
            "participantCount": len(cached_data),
            "refreshedAt": datetime.utcnow().isoformat() + "Z",
        }

    except Exception as e:
        logger.error(f"[Scheduler] Failed to refresh cache: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Participant Endpoints
# ============================================================================

@app.get("/api/participants")
@limiter.limit("60/minute")
def get_participants(request: Request, user: dict = Depends(verify_firebase_token)):
    """Get list of all enrolled participants from both collections."""
    try:
        # Use the helper function with enrolled_only filter
        participants_info = get_all_participant_ids(enrolled_only=True)

        participants = []
        for p_info in participants_info:
            data = p_info["data"]
            enrolled_at = p_info["enrolledAt"]

            # Convert string dates to datetime if needed
            if enrolled_at and isinstance(enrolled_at, str):
                try:
                    enrolled_at = datetime.fromisoformat(enrolled_at.replace("Z", "+00:00"))
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

            participants.append({
                "id": p_info["id"],
                "participantId": data.get("participantId", p_info["id"]),
                "enrolledAt": enrolled_at,
                "deviceModel": data.get("deviceModel", "Unknown"),
                "osVersion": data.get("osVersion", "Unknown"),
                "isTestUser": data.get("isTestUser", False),
            })

        # Sort by enrolledAt, handling None values
        def sort_key(x):
            enrolled = x.get("enrolledAt")
            if enrolled is None:
                return ""
            if hasattr(enrolled, 'isoformat'):
                return enrolled.isoformat()
            return str(enrolled)

        return sorted(participants, key=sort_key, reverse=True)
    except Exception as e:
        logger.error(f"Failed to get participants: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/overall_status")
@limiter.limit("30/minute")
def get_overall_status(
    request: Request,
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("compliance", description="compliance | reddit | twitter | id"),
    sort_dir: str = Query("desc", description="asc | desc"),
    user: dict = Depends(verify_firebase_token)
):
    """
    Get overall status for participants within date range (paginated).
    Reads from hourly-refreshed cache for performance.
    Returns daily indicators: screenshots, OCR extractions, check-ins, safety alerts.
    """
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        # Try to read from cache first
        cache_ref = db.collection(DASHBOARD_CACHE_COLLECTION).document("overall_status")
        cache_doc = cache_ref.get()

        if cache_doc.exists:
            cache_data = cache_doc.to_dict()
            cached_participants = cache_data.get("participants", [])
            refreshed_at = cache_data.get("refreshedAt")

            if refreshed_at and hasattr(refreshed_at, 'timestamp'):
                refreshed_at = datetime.fromtimestamp(refreshed_at.timestamp())

            # Filter daily status to requested date range
            results = []
            for p in cached_participants:
                daily_status = p.get("dailyStatus", [])
                filtered_daily = [
                    d for d in daily_status
                    if start_date <= d.get("date", "") <= end_date
                ]

                # Recalculate totals for the filtered range
                total_screenshots = sum(d.get("screenshots", 0) for d in filtered_daily)
                total_checkins = sum(d.get("checkins", 0) for d in filtered_daily)
                total_reddit = sum(d.get("reddit", 0) for d in filtered_daily)
                total_twitter = sum(d.get("twitter", 0) for d in filtered_daily)
                days_count = max(1, len(filtered_daily))

                # Calculate if participant is active
                # First check for manual override in participant doc
                pid = p.get("id")
                manual_status = None
                try:
                    # Check valid_participants first, then participants
                    p_doc = db.collection(config.col("valid_participants")).document(pid).get()
                    if not p_doc.exists:
                        p_doc = db.collection(config.col("participants")).document(pid).get()
                    if p_doc.exists:
                        p_data = p_doc.to_dict()
                        manual_status = p_data.get("manualActiveStatus")
                except Exception:
                    pass  # Ignore errors, fall back to auto-calculation

                if manual_status is not None:
                    is_active = manual_status
                else:
                    # Auto-calculate based on 90-day window
                    study_start_str = p.get("study_start_date")
                    if study_start_str:
                        try:
                            p_study_start = datetime.strptime(study_start_str, "%Y-%m-%d")
                            days_since_start = (datetime.now() - p_study_start).days
                            is_active = days_since_start <= 90
                        except (ValueError, TypeError):
                            is_active = True  # Default to active if can't parse
                    else:
                        is_active = True  # Default to active if no start date

                results.append({
                    "id": pid,
                    "study_start_date": p.get("study_start_date"),
                    "is_active": is_active,
                    "dailyStatus": filtered_daily,
                    "weeklyScreenshots": total_screenshots,
                    "weeklyCheckins": total_checkins,
                    "weeklyReddit": total_reddit,
                    "weeklyTwitter": total_twitter,
                    "overallCompliance": min(100, int((total_checkins / (days_count * config.EMA_PROMPTS_PER_DAY)) * 100)) if days_count > 0 else 0,
                })

            # Sort the FULL result set BEFORE paginating, so e.g. "lowest
            # compliance first" surfaces the genuinely lowest participants across
            # all pages — not just a reordering of the current 25-row page.
            _sort_fields = {
                "compliance": "overallCompliance",
                "reddit": "weeklyReddit",
                "twitter": "weeklyTwitter",
                "id": "id",
            }
            _field = _sort_fields.get(sort_by, "overallCompliance")
            _reverse = (sort_dir or "desc").lower() != "asc"
            if _field == "id":
                results.sort(key=lambda r: str(r.get("id", "")), reverse=_reverse)
            else:
                results.sort(key=lambda r: r.get(_field) or 0, reverse=_reverse)

            # Paginate results
            total_participants = len(results)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_results = results[start_idx:end_idx]

            return {
                "participants": paginated_results,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total_participants,
                    "total_pages": (total_participants + page_size - 1) // page_size,
                },
                "cache": {
                    "fromCache": True,
                    "refreshedAt": (refreshed_at.isoformat() + "Z") if refreshed_at else None,
                }
            }

        # Cache miss - compute live (but recommend cache refresh)
        logger.warning("Cache miss for overall_status - computing live")

        # Fall back to live computation (same as before but simplified)
        participants_info = get_all_participant_ids()
        total_participants = len(participants_info)

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_participants = participants_info[start_idx:end_idx]

        results = []
        for p_info in paginated_participants:
            pid = p_info["id"]
            enrolled_at = p_info["enrolledAt"]

            if enrolled_at:
                if hasattr(enrolled_at, 'timestamp'):
                    study_start = datetime.fromtimestamp(enrolled_at.timestamp())
                else:
                    study_start = enrolled_at
            else:
                study_start = start_dt

            # Use the helper function for computing stats
            daily_status = compute_participant_stats(pid, start_dt, end_dt)

            # Calculate totals
            total_screenshots = sum(d.get("screenshots", 0) for d in daily_status.values())
            total_checkins = sum(d.get("checkins", 0) for d in daily_status.values())
            total_reddit = sum(d.get("reddit", 0) for d in daily_status.values())
            total_twitter = sum(d.get("twitter", 0) for d in daily_status.values())
            days_count = max(1, len(daily_status))

            # Build daily status list
            daily_list = []
            current = start_dt
            while current <= end_dt:
                date_str = current.strftime("%Y-%m-%d")
                day_data = daily_status.get(date_str, {
                    "screenshots": 0, "ocr_chars": 0, "checkins": 0, "safety_alerts": 0,
                    "reddit": 0, "twitter": 0, "crisis_indicated": False
                })
                daily_list.append({"date": date_str, **day_data})
                current += timedelta(days=1)

            # Calculate if participant is active
            # First check for manual override
            p_data = p_info.get("data", {})
            manual_status = p_data.get("manualActiveStatus") if p_data else None

            if manual_status is not None:
                is_active = manual_status
            elif study_start:
                days_since_start = (datetime.now() - study_start).days
                is_active = days_since_start <= 90
            else:
                is_active = True  # Default to active if no start date

            results.append({
                "id": pid,
                "study_start_date": study_start.strftime("%Y-%m-%d") if study_start else None,
                "is_active": is_active,
                "dailyStatus": daily_list,
                "weeklyScreenshots": total_screenshots,
                "weeklyCheckins": total_checkins,
                "weeklyReddit": total_reddit,
                "weeklyTwitter": total_twitter,
                "overallCompliance": min(100, int((total_checkins / (days_count * config.EMA_PROMPTS_PER_DAY)) * 100)) if days_count > 0 else 0,
                # Surfaces a dashboard warning when a device's local capture is
                # paused on a full cache (data-loss risk; usually a long offline gap).
                "captureDiskPaused": (p_info.get("data") or {}).get("captureDiskPaused", False),
            })

        return {
            "participants": results,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total_participants,
                "total_pages": (total_participants + page_size - 1) // page_size,
            },
            "cache": {
                "fromCache": False,
                "message": "Cache not available. Admin should run refresh.",
            }
        }

    except Exception as e:
        logger.error(f"Failed to get overall status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/safety-alerts")
@limiter.limit("60/minute")
async def get_safety_alerts(request: Request, user: dict = Depends(verify_firebase_token)):
    """
    Get safety alerts from the in-memory cache.
    Cache is refreshed every 2 minutes by a background task.
    Returns cached data for fast response times.
    """
    async with _safety_alert_lock:
        payload = SAFETY_ALERT_CACHE.copy()

    if payload["status"] == "never_run":
        # Cache not yet initialized — fetch live instead of returning 503
        try:
            loop = asyncio.get_event_loop()
            alerts = await loop.run_in_executor(None, fetch_live_safety_alerts)

            async with _safety_alert_lock:
                SAFETY_ALERT_CACHE.update({
                    "alerts": alerts,
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                    "status": "ok",
                    "error": None,
                })

            logger.info(f"[SafetyAlerts] Initial fetch on first request: {len(alerts)} alerts")
            return {
                "alerts": alerts,
                "fromCache": False,
                "refreshedAt": SAFETY_ALERT_CACHE["updated_at"],
                "status": "ok",
                "error": None,
                "refreshIntervalSeconds": SAFETY_ALERT_REFRESH_SECONDS,
            }
        except Exception as e:
            logger.error(f"[SafetyAlerts] Initial fetch failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch safety alerts: {str(e)}"
            )

    return {
        "alerts": payload["alerts"],
        "fromCache": True,
        "refreshedAt": payload["updated_at"],
        "status": payload["status"],
        "error": payload["error"],
        "refreshIntervalSeconds": SAFETY_ALERT_REFRESH_SECONDS,
    }


@app.post("/api/safety-alerts/refresh")
@limiter.limit("5/minute")
async def force_refresh_safety_alerts(request: Request, user: dict = Depends(verify_admin_token)):
    """
    Force an immediate refresh of the safety alerts cache.
    Admin only. Use when you need to see alerts immediately without waiting
    for the 2-minute refresh cycle.
    """
    try:
        # Run the blocking Firestore call in a thread pool
        loop = asyncio.get_event_loop()
        alerts = await loop.run_in_executor(None, fetch_live_safety_alerts)

        async with _safety_alert_lock:
            SAFETY_ALERT_CACHE.update({
                "alerts": alerts,
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "status": "ok",
                "error": None,
            })

        logger.info(f"[SafetyAlerts] Manual refresh completed: {len(alerts)} alerts")

        return {
            "status": "ok",
            "count": len(alerts),
            "refreshedAt": SAFETY_ALERT_CACHE["updated_at"],
        }

    except Exception as e:
        logger.error(f"[SafetyAlerts] Manual refresh failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/participant/{participant_id}/summary")
@limiter.limit("30/minute")
def get_participant_summary(request: Request, participant_id: str, user: dict = Depends(verify_firebase_token)):
    """Get detailed summary for a single participant."""
    try:
        # Get participant info from either collection
        participant_data = get_participant_data(participant_id)

        # Get reference for subcollections (always under participants/{id})
        participant_ref = get_participant_ref(participant_id)

        # Check if participant exists (in either collection or has events)
        if not participant_data:
            # Check if there are events even without metadata doc
            events_check = list(participant_ref.collection("events").limit(1).stream())
            if not events_check:
                # Also check for safety_alerts or ema_responses
                alerts_check = list(participant_ref.collection("safety_alerts").limit(1).stream())
                ema_check = list(participant_ref.collection("ema_responses").limit(1).stream())
                if not alerts_check and not ema_check:
                    raise HTTPException(status_code=404, detail="Participant not found")
            participant_data = {}

        # Check for manually set study start date first, then fall back to enrollment date
        custom_start = participant_data.get("studyStartDate")
        enrolled_at = participant_data.get("enrolledAt") or participant_data.get("lastEnrolledAt")

        if custom_start:
            # Custom study start date was set by researcher
            if hasattr(custom_start, 'timestamp'):
                study_start = datetime.fromtimestamp(custom_start.timestamp())
            elif isinstance(custom_start, str):
                study_start = datetime.strptime(custom_start, "%Y-%m-%d")
            else:
                study_start = custom_start
            study_start_is_custom = True
        elif enrolled_at:
            if hasattr(enrolled_at, 'timestamp'):
                study_start = datetime.fromtimestamp(enrolled_at.timestamp())
            else:
                study_start = enrolled_at
            study_start_is_custom = False
        else:
            study_start = datetime.now() - timedelta(days=30)
            study_start_is_custom = False

        # Get all events for this participant - use 'timestamp' field
        events_ref = participant_ref.collection("events")
        events = list(events_ref.order_by("timestamp").stream())

        # Aggregate by day
        daily_summaries = defaultdict(lambda: {
            "screenshots": 0,
            "ocr_chars": 0,
            "ocr_words": 0,
            "platforms": defaultdict(int),
            "checkins": 0,
            "safety_alerts": 0,
        })

        for event_doc in events:
            event = event_doc.to_dict()
            # Events use 'timestamp' or 'createdAt', not 'capturedAt'
            captured_at = event.get("timestamp") or event.get("createdAt")
            if not captured_at:
                continue

            # Handle various timestamp formats
            if hasattr(captured_at, 'timestamp'):
                event_date = datetime.fromtimestamp(captured_at.timestamp()).strftime("%Y-%m-%d")
            elif isinstance(captured_at, str):
                event_date = captured_at[:10]  # Extract YYYY-MM-DD from ISO string
            else:
                event_date = captured_at.strftime("%Y-%m-%d")

            # Events use 'eventType' field, not 'type'
            event_type = event.get("eventType", event.get("type", ""))

            if event_type == "screenshot":
                daily_summaries[event_date]["screenshots"] += 1
                platform = event.get("platform", "unknown")
                daily_summaries[event_date]["platforms"][platform] += 1

                ocr = event.get("ocr", {})
                if ocr:
                    daily_summaries[event_date]["ocr_words"] += ocr.get("wordCount", 0)
                    daily_summaries[event_date]["ocr_chars"] += ocr.get("wordCount", 0) * 5

        # Get check-ins
        try:
            checkins_ref = participant_ref.collection("ema_responses")
            for checkin_doc in checkins_ref.stream():
                checkin = checkin_doc.to_dict()
                completed_at = checkin.get("completedAt")
                if completed_at:
                    # Handle various timestamp formats
                    if hasattr(completed_at, 'timestamp'):
                        checkin_date = datetime.fromtimestamp(completed_at.timestamp()).strftime("%Y-%m-%d")
                    elif isinstance(completed_at, str):
                        checkin_date = completed_at[:10]
                    else:
                        checkin_date = completed_at.strftime("%Y-%m-%d")
                    daily_summaries[checkin_date]["checkins"] += 1

                    # Parse responses - may be JSON string or dict
                    responses = checkin.get("responses", {})
                    if isinstance(responses, str):
                        try:
                            responses = json.loads(responses)
                        except (json.JSONDecodeError, TypeError, ValueError):
                            responses = {}

                    # Check for crisis indicator in responses
                    for key, value in responses.items():
                        if isinstance(value, str) and value.lower() in ("yes", "true"):
                            if "crisis" in key.lower() or "harm" in key.lower() or "hurt" in key.lower():
                                if "crisis_indicated" not in daily_summaries[checkin_date]:
                                    daily_summaries[checkin_date]["crisis_indicated"] = False
                                daily_summaries[checkin_date]["crisis_indicated"] = True
        except Exception as e:
            logger.debug(f"Silently handled exception: {e}")

        # Get safety alerts
        try:
            alerts_ref = participant_ref.collection("safety_alerts")
            for alert_doc in alerts_ref.stream():
                alert = alert_doc.to_dict()
                triggered_at = alert.get("triggeredAt")
                if triggered_at:
                    # Handle various timestamp formats
                    if hasattr(triggered_at, 'timestamp'):
                        alert_date = datetime.fromtimestamp(triggered_at.timestamp()).strftime("%Y-%m-%d")
                    elif isinstance(triggered_at, str):
                        alert_date = triggered_at[:10]
                    else:
                        alert_date = triggered_at.strftime("%Y-%m-%d")
                    daily_summaries[alert_date]["safety_alerts"] += 1
        except Exception as e:
            logger.debug(f"Silently handled exception: {e}")

        # Convert to list sorted by date
        summary_list = []
        for date_str, data in sorted(daily_summaries.items()):
            summary_list.append({
                "pid": participant_id,
                "date": date_str,
                "screenshots": data["screenshots"],
                "ocr_words": data["ocr_words"],
                "reddit": data["platforms"].get("reddit", 0),
                "twitter": data["platforms"].get("twitter", 0),
                "checkins": data["checkins"],
                "safety_alerts": data["safety_alerts"],
                "crisis_indicated": data.get("crisis_indicated", False),
            })

        # Calculate if participant is active
        # First check for manual override, then fall back to 90-day calculation
        days_since_start = (datetime.now() - study_start).days
        study_day = days_since_start + 1  # Day 1 is the start date

        manual_status = participant_data.get("manualActiveStatus")
        if manual_status is not None:
            # Manual override exists
            is_active = manual_status
            is_active_manual = True
            inactive_reason = participant_data.get("manualActiveStatusReason")
        else:
            # Auto-calculate based on 90-day window
            is_active = days_since_start <= 90
            is_active_manual = False
            inactive_reason = None

        return {
            "participant_id": participant_id,
            "study_start_date": study_start.strftime("%Y-%m-%d"),
            "study_start_is_custom": study_start_is_custom,
            "is_active": is_active,
            "is_active_manual": is_active_manual,
            "inactive_reason": inactive_reason,
            "study_day": min(study_day, 90) if is_active else 90,
            "days_remaining": max(0, 90 - days_since_start) if is_active else 0,
            "device_model": participant_data.get("deviceModel"),
            "os_version": participant_data.get("osVersion"),
            "daily_summary": summary_list
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get participant summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class UpdateStudyStartRequest(BaseModel):
    study_start_date: str  # Format: YYYY-MM-DD


@app.put("/api/participant/{participant_id}/study-start-date")
@limiter.limit("30/minute")
def update_study_start_date(
    request: Request,
    participant_id: str,
    body: UpdateStudyStartRequest,
    user: dict = Depends(verify_firebase_token),
):
    """
    Update the study start date for a participant.
    This allows researchers to adjust when the 90-day study period begins,
    for example if a participant had a partial onboarding.
    """
    try:
        # Validate date format
        try:
            new_start_date = datetime.strptime(body.study_start_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

        # Don't allow future dates
        if new_start_date > datetime.now():
            raise HTTPException(status_code=400, detail="Study start date cannot be in the future.")

        # Get participant reference - check both collections
        participant_ref = None
        valid_ref = db.collection(config.col("valid_participants")).document(participant_id)
        participants_ref = db.collection(config.col("participants")).document(participant_id)

        # Check which collection has the participant
        if valid_ref.get().exists:
            participant_ref = valid_ref
        elif participants_ref.get().exists:
            participant_ref = participants_ref
        else:
            # Check if participant has any data (events, etc.)
            events_check = list(participants_ref.collection("events").limit(1).stream())
            if events_check:
                # Participant exists via events, create/update in participants collection
                participant_ref = participants_ref
            else:
                raise HTTPException(status_code=404, detail="Participant not found")

        # Update the study start date
        participant_ref.set({
            "studyStartDate": body.study_start_date,
            "studyStartDateUpdatedAt": datetime.utcnow(),
            "studyStartDateUpdatedBy": user.get("email"),
        }, merge=True)

        logger.info(f"Study start date updated for {participant_id} to {body.study_start_date} by {user.get('email')}")

        return {
            "participant_id": participant_id,
            "study_start_date": body.study_start_date,
            "updated_by": user.get("email"),
            "message": "Study start date updated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update study start date: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class UpdateActiveStatusRequest(BaseModel):
    is_active: bool
    reason: Optional[str] = None  # Optional reason for the change (e.g., "dropped out", "device issue")


@app.put("/api/participant/{participant_id}/active-status")
@limiter.limit("30/minute")
def update_active_status(
    request: Request,
    participant_id: str,
    body: UpdateActiveStatusRequest,
    user: dict = Depends(verify_firebase_token),
):
    """
    Manually set a participant's active/inactive status.
    This overrides the automatic 90-day calculation.
    Use this when a participant drops out early or needs to be reactivated.
    """
    try:
        # Get participant reference - check both collections
        participant_ref = None
        valid_ref = db.collection(config.col("valid_participants")).document(participant_id)
        participants_ref = db.collection(config.col("participants")).document(participant_id)

        # Check which collection has the participant
        if valid_ref.get().exists:
            participant_ref = valid_ref
        elif participants_ref.get().exists:
            participant_ref = participants_ref
        else:
            # Check if participant has any data (events, etc.)
            events_check = list(participants_ref.collection("events").limit(1).stream())
            if events_check:
                participant_ref = participants_ref
            else:
                raise HTTPException(status_code=404, detail="Participant not found")

        # Update the active status
        update_data = {
            "manualActiveStatus": body.is_active,
            "manualActiveStatusUpdatedAt": datetime.utcnow(),
            "manualActiveStatusUpdatedBy": user.get("email"),
        }
        if body.reason:
            update_data["manualActiveStatusReason"] = body.reason

        participant_ref.set(update_data, merge=True)

        status_str = "active" if body.is_active else "inactive"
        logger.info(f"Active status for {participant_id} set to {status_str} by {user.get('email')}")

        return {
            "participant_id": participant_id,
            "is_active": body.is_active,
            "reason": body.reason,
            "updated_by": user.get("email"),
            "message": f"Participant marked as {status_str}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update active status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/participant/{participant_id}/day/{date}")
@limiter.limit("30/minute")
def get_day_detail(request: Request, participant_id: str, date: str, user: dict = Depends(verify_firebase_token)):
    """Get detailed data for a specific participant on a specific day."""
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d")
        next_date = target_date + timedelta(days=1)

        # Get participant data from either collection
        participant_data = get_participant_data(participant_id)

        # Get reference for subcollections (always under participants/{id})
        participant_ref = get_participant_ref(participant_id)

        # Verify participant exists (in either collection or has data)
        if not participant_data:
            # Check if there's any data for this participant
            events_check = list(participant_ref.collection("events").limit(1).stream())
            alerts_check = list(participant_ref.collection("safety_alerts").limit(1).stream())
            ema_check = list(participant_ref.collection("ema_responses").limit(1).stream())
            if not events_check and not alerts_check and not ema_check:
                raise HTTPException(status_code=404, detail="Participant not found")

        # Get events for this day - timestamps are Firestore DatetimeWithNanoseconds
        events_ref = participant_ref.collection("events")

        # Query using datetime objects
        events_query = events_ref.where(
            "timestamp", ">=", target_date
        ).where(
            "timestamp", "<", next_date
        ).order_by("timestamp")

        events = []
        hourly_counts = defaultdict(lambda: {
            "screenshots": 0, "ocr_words": 0, "reddit": 0, "twitter": 0
        })
        platform_totals = {"reddit": 0, "twitter": 0, "other": 0}

        for event_doc in events_query.stream():
            event = event_doc.to_dict()
            # Use 'timestamp' or 'createdAt'
            captured_at = event.get("timestamp") or event.get("createdAt")

            # Parse timestamp to datetime
            if hasattr(captured_at, 'timestamp'):
                ts = datetime.fromtimestamp(captured_at.timestamp())
            elif isinstance(captured_at, str):
                ts = datetime.fromisoformat(captured_at.replace("Z", "+00:00").replace("+00:00", ""))
            else:
                ts = captured_at

            # Only count screenshots, not page_views or content_exposures
            event_type = event.get("eventType", event.get("type", ""))
            if event_type == "screenshot":
                hour = ts.hour
                hourly_counts[hour]["screenshots"] += 1

                # Track platform breakdown
                platform = event.get("platform", "").lower()
                if platform == "reddit":
                    hourly_counts[hour]["reddit"] += 1
                    platform_totals["reddit"] += 1
                elif platform in ("twitter", "x"):
                    hourly_counts[hour]["twitter"] += 1
                    platform_totals["twitter"] += 1
                else:
                    platform_totals["other"] += 1

                ocr = event.get("ocr", {})
                if ocr:
                    hourly_counts[hour]["ocr_words"] += ocr.get("wordCount", 0)

            events.append({
                "id": event_doc.id,
                "timestamp": ts.isoformat() if ts else None,
                "type": event_type,
                "platform": event.get("platform"),
                "url": event.get("url"),
                "ocr_word_count": event.get("ocr", {}).get("wordCount", 0) if event.get("ocr") else 0,
                "ocr_text": event.get("ocr", {}).get("extractedText", "") if event.get("ocr") else "",
                "screenshot_url": event.get("screenshotUrl"),
            })

        # Get check-ins for this day
        checkins = []
        crisis_indicated = False
        try:
            checkins_ref = participant_ref.collection("ema_responses")
            # completedAt is Firestore DatetimeWithNanoseconds
            checkins_query = checkins_ref.where(
                "completedAt", ">=", target_date
            ).where(
                "completedAt", "<", next_date
            )

            for checkin_doc in checkins_query.stream():
                checkin = checkin_doc.to_dict()
                completed_at = checkin.get("completedAt")

                # Parse timestamp
                if hasattr(completed_at, 'timestamp'):
                    ts = datetime.fromtimestamp(completed_at.timestamp())
                elif isinstance(completed_at, str):
                    ts = datetime.fromisoformat(completed_at.replace("Z", "+00:00").replace("+00:00", ""))
                else:
                    ts = completed_at

                # Parse responses - may be JSON string
                responses = checkin.get("responses", {})
                if isinstance(responses, str):
                    try:
                        responses = json.loads(responses)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        responses = {}

                # Check for crisis indicator in responses
                checkin_has_crisis = False
                for key, value in responses.items():
                    if isinstance(value, str) and value.lower() in ("yes", "true"):
                        if "crisis" in key.lower() or "harm" in key.lower() or "hurt" in key.lower():
                            checkin_has_crisis = True
                            crisis_indicated = True

                checkins.append({
                    "id": checkin_doc.id,
                    "sessionId": checkin.get("sessionId"),
                    "timestamp": ts.isoformat() if ts else None,
                    "time": ts.strftime("%I:%M %p") if ts else None,
                    "responses": responses,
                    "crisis_indicated": checkin_has_crisis,
                    "selfInitiated": checkin.get("selfInitiated", False),
                })
        except Exception as e:
            logger.warning(f"Error fetching checkins for day: {e}")

        # Get safety alerts for this day
        # Also match with corresponding EMA responses for full SI data
        safety_alerts = []
        try:
            alerts_ref = participant_ref.collection("safety_alerts")
            # Safety alerts use Firestore timestamps, not ISO strings
            alerts_query = alerts_ref.where(
                "triggeredAt", ">=", target_date
            ).where(
                "triggeredAt", "<", next_date
            )

            # Build a map of sessionId -> EMA responses for matching
            ema_by_session = {}
            for checkin in checkins:
                if checkin.get("sessionId"):
                    ema_by_session[checkin["sessionId"]] = checkin.get("responses", {})
            # Also check the raw checkin data for sessionId
            try:
                checkins_ref = participant_ref.collection("ema_responses")
                for ema_doc in checkins_ref.stream():
                    ema_data = ema_doc.to_dict()
                    session_id = ema_data.get("sessionId")
                    if session_id and session_id not in ema_by_session:
                        responses = ema_data.get("responses", {})
                        if isinstance(responses, str):
                            try:
                                responses = json.loads(responses)
                            except (json.JSONDecodeError, TypeError, ValueError):
                                responses = {}
                        ema_by_session[session_id] = responses
            except Exception as e:
                logger.debug(f"Silently handled exception: {e}")

            for alert_doc in alerts_query.stream():
                alert = alert_doc.to_dict()
                triggered_at = alert.get("triggeredAt")
                session_id = alert.get("sessionId")

                # Handle various timestamp formats
                if hasattr(triggered_at, 'timestamp'):
                    ts = datetime.fromtimestamp(triggered_at.timestamp())
                elif isinstance(triggered_at, str):
                    ts = datetime.fromisoformat(triggered_at.replace("Z", "+00:00").replace("+00:00", ""))
                else:
                    ts = triggered_at

                # Get alert's partial responses
                alert_responses = alert.get("responses", {})

                # Try to get full responses from matching EMA
                full_responses = ema_by_session.get(session_id, {})

                # Merge: use full EMA responses, but fall back to alert responses if not in EMA
                merged_responses = {**alert_responses, **full_responses}

                safety_alerts.append({
                    "id": alert_doc.id,
                    "timestamp": ts.isoformat() if ts else None,
                    "time": ts.strftime("%I:%M %p") if ts else None,
                    "handled": alert.get("handled", False),
                    "responses": merged_responses,
                    "sessionId": session_id,
                })
        except Exception as e:
            logger.warning(f"Error fetching safety alerts for day: {e}")

        # Get notification log for this day
        notification_log = []
        try:
            notif_ref = participant_ref.collection("notification_log")
            notif_query = notif_ref.where(
                "timestamp", ">=", target_date
            ).where(
                "timestamp", "<", next_date
            ).order_by("timestamp")

            for notif_doc in notif_query.stream():
                notif = notif_doc.to_dict()
                notif_ts = notif.get("timestamp")
                if hasattr(notif_ts, 'timestamp'):
                    notif_ts = datetime.fromtimestamp(notif_ts.timestamp())

                notification_log.append({
                    "id": notif_doc.id,
                    "eventType": notif.get("eventType"),
                    "timestamp": notif_ts.isoformat() if notif_ts else None,
                    "time": notif_ts.strftime("%I:%M %p") if notif_ts else None,
                    "localTime": notif.get("localTime"),
                    "data": notif.get("data", {}),
                })
        except Exception as e:
            logger.warning(f"Error fetching notification log for day: {e}")

        # Build hourly activity for charts (keyed by hour integer 0-23)
        hourly_activity = {}
        for hour in range(24):
            counts = hourly_counts.get(hour, {"screenshots": 0, "ocr_words": 0, "reddit": 0, "twitter": 0})
            hourly_activity[hour] = {
                "screenshots": counts["screenshots"],
                "ocr_words": counts["ocr_words"],
                "reddit": counts["reddit"],
                "twitter": counts["twitter"],
            }

        # Count only actual screenshots, not all events
        screenshot_events = [e for e in events if e.get("type") == "screenshot"]

        # Build sample screenshots by hour for preview (max 10 per hour)
        hourly_screenshots = defaultdict(list)
        for event in screenshot_events:
            if event.get("screenshot_url"):
                ts_str = event.get("timestamp")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00").replace("+00:00", ""))
                        hour = ts.hour
                        hourly_screenshots[hour].append({
                            "url": event["screenshot_url"],
                            "timestamp": ts_str,
                            "platform": event.get("platform"),
                            "time": ts.strftime("%I:%M %p"),
                        })
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass

        # Sample ~10 screenshots per hour (evenly distributed)
        sample_screenshots_by_hour = {}
        for hour, screenshots in hourly_screenshots.items():
            if len(screenshots) <= 10:
                sample_screenshots_by_hour[hour] = screenshots
            else:
                # Take evenly spaced samples
                step = len(screenshots) / 10
                sample_screenshots_by_hour[hour] = [
                    screenshots[int(i * step)] for i in range(10)
                ]

        # Also create a flat list of ~10 screenshots across the whole day
        all_screenshots = []
        for hour in sorted(hourly_screenshots.keys()):
            all_screenshots.extend(hourly_screenshots[hour])

        if len(all_screenshots) <= 10:
            day_sample_screenshots = all_screenshots
        else:
            step = len(all_screenshots) / 10
            day_sample_screenshots = [
                all_screenshots[int(i * step)] for i in range(10)
            ]

        return {
            "participant_id": participant_id,
            "date": date,
            "total_screenshots": len(screenshot_events),
            "total_ocr_words": sum(e.get("ocr_word_count", 0) for e in screenshot_events),
            "reddit_screenshots": platform_totals["reddit"],
            "twitter_screenshots": platform_totals["twitter"],
            "crisis_indicated": crisis_indicated,
            "hourly_activity": hourly_activity,
            "platform_breakdown": {
                "reddit": {"screenshots": platform_totals["reddit"]},
                "twitter": {"screenshots": platform_totals["twitter"]},
                "other": {"screenshots": platform_totals["other"]},
            },
            "events": events[:100],  # Limit to 100 events for performance
            "checkins": checkins,
            "safety_alerts": safety_alerts,
            "notification_log": notification_log,
            "sample_screenshots_by_hour": sample_screenshots_by_hour,
            "sample_screenshots": day_sample_screenshots,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get day detail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Data Export
# ============================================================================

EXPORT_DIR = Path(config.EXPORT_DIR)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_INDEX = {}

# Firebase Storage for downloading screenshots
from firebase_admin import storage as fb_storage
import threading
import requests
import google.auth
from google.auth.transport import requests as google_requests


def get_storage_bucket():
    """Get Firebase Storage bucket.

    This project uses the newer .firebasestorage.app bucket naming.
    Verified via: gsutil ls -> gs://r01-redditx-suicide.firebasestorage.app/
    """
    bucket_name = f"{config.FIREBASE_PROJECT_ID}.firebasestorage.app"
    try:
        bucket = fb_storage.bucket(bucket_name)
        logger.debug(f"Using storage bucket: {bucket_name}")
        return bucket
    except Exception as e:
        logger.error(f"Failed to initialize storage bucket {bucket_name}: {e}")
        raise


def read_content_events_from_gcs(participant_id, start_dt=None, end_dt=None):
    """Read offloaded analytics events (content_visible / content_exposure) from
    Cloud Storage and return them as event dicts shaped like Firestore events.

    The Flutter app offloads these high-frequency types to gzipped JSONL objects
    under content_events/{participantId}/{sessionId}/*.jsonl.gz instead of one
    Firestore doc each. Exports merge them back in so the researcher view is
    complete regardless of where an event physically lives.

    Transition-safe: legacy content events still in Firestore are returned by the
    normal events query; this only adds the GCS-resident ones. Dedup by event id
    guards against any overlap during the migration window.

    Memory: streams one object at a time, decompresses, parses line-by-line.
    Objects are ~5–15 KB each. Pure decode/filter/dedup live in content_events.py
    (unit-tested); this function owns only the GCS I/O.
    """
    events = []
    try:
        bucket = get_storage_bucket()
    except Exception as e:
        logger.warning(f"content_events: could not get bucket for {participant_id}: {e}")
        return events

    prefix = f"content_events/{participant_id}/"
    try:
        blobs = list(bucket.list_blobs(prefix=prefix))
    except Exception as e:
        logger.warning(f"content_events: list_blobs failed for {prefix}: {e}")
        return events

    for blob in blobs:
        if not blob.name.endswith(".jsonl.gz"):
            continue
        try:
            # raw_download=True bypasses GCS decompressive transcoding so we
            # always get the stored gzip bytes regardless of object metadata.
            raw = blob.download_as_bytes(raw_download=True)
        except Exception as e:
            logger.warning(f"content_events: failed to read {blob.name}: {e}")
            continue
        for ev in content_events_mod.parse_jsonl_gz(raw):
            if content_events_mod.event_in_window(ev, start_dt, end_dt):
                events.append(ev)

    if events:
        logger.info(f"content_events: merged {len(events)} offloaded events for {participant_id}")
    return events


def merge_content_events(events_data, participant_id, start_dt=None, end_dt=None):
    """Append GCS-offloaded content events to an export's events_data list,
    de-duplicating by id against what's already present (legacy Firestore copies).
    Mutates and returns events_data."""
    return content_events_mod.merge_content_events(
        events_data, read_content_events_from_gcs(participant_id, start_dt, end_dt)
    )


def get_signing_credentials():
    """Get credentials for signing URLs in Cloud Run.

    Cloud Run uses Compute Engine credentials which don't have private keys.
    We need to get the access token and service account email to use
    IAM-based signing via the signBlob API.

    Returns:
        tuple: (service_account_email, access_token)
    """
    credentials, project = google.auth.default()

    # Refresh credentials to get a valid access token
    auth_request = google_requests.Request()
    credentials.refresh(auth_request)

    # Get the service account email
    service_account_email = getattr(credentials, 'service_account_email', None)
    if not service_account_email:
        # Fallback for compute engine credentials
        service_account_email = f"{config.FIREBASE_PROJECT_ID.replace('-', '')}@appspot.gserviceaccount.com"
        # Actually use the compute service account
        service_account_email = "436153481478-compute@developer.gserviceaccount.com"

    return service_account_email, credentials.token


# Shared session for HTTP downloads (connection reuse)
_download_session = None

def get_download_session():
    """Get a shared requests session for connection reuse."""
    global _download_session
    if _download_session is None:
        _download_session = requests.Session()
        # Configure connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=2
        )
        _download_session.mount('https://', adapter)
        _download_session.mount('http://', adapter)
    return _download_session


def extract_storage_path_from_url(url: str) -> Optional[str]:
    """Extract Firebase Storage blob path from a download URL."""
    if not url:
        return None
    # Firebase Storage URLs: https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{encoded_path}?alt=media&token=...
    match = re.search(r'/o/([^?]+)', url)
    if match:
        return unquote(match.group(1))
    return None


# ============================================================================
# JPEG XL support — screenshots are stored as byte-exact reversible .jxl
# (converted by the convertScreenshotsToJxl Cloud Function). djxl reconstructs
# the IDENTICAL original .jpg file. The vendored static binary lives in bin/.
# ============================================================================

DJXL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "djxl")


def reconstruct_jpeg_from_jxl(jxl_bytes: bytes) -> bytes:
    """Byte-exact reconstruction of the original JPEG from a JXL container."""
    import subprocess
    import tempfile

    try:
        os.chmod(DJXL_PATH, 0o755)
    except OSError:
        pass

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.jxl")
        dst = os.path.join(tmp, "out.jpg")
        with open(src, "wb") as f:
            f.write(jxl_bytes)
        subprocess.run([DJXL_PATH, src, dst], check=True, capture_output=True, timeout=30)
        with open(dst, "rb") as f:
            return f.read()


def _proxy_url_storage_path(url: str) -> Optional[str]:
    """Extract the storage path from a /api/screenshot-view proxy URL."""
    if "/api/screenshot-view" not in (url or ""):
        return None
    from urllib.parse import urlparse, parse_qs
    try:
        qs = parse_qs(urlparse(url).query)
        return qs.get("path", [None])[0]
    except Exception:
        return None


def download_single_screenshot(ss_info: Dict[str, Any], bucket, session) -> Tuple[str, Optional[bytes], str]:
    """
    Download a single screenshot, trying Storage API first, then HTTP.
    JXL-stored screenshots are reconstructed to their byte-exact original JPEG.
    Returns: (event_id, image_bytes or None, extension)
    """
    event_id = ss_info.get("event_id", "unknown")
    url = ss_info.get("url", "")
    storage_path = ss_info.get("storagePath")  # Direct path if available

    # Proxy URLs (post-JXL-conversion) carry the storage path as a query param
    if not storage_path:
        storage_path = _proxy_url_storage_path(url)

    img_data = None
    ext = ".jpg"

    try:
        # Try Storage API first if we have a path
        if storage_path and bucket:
            try:
                blob = bucket.blob(storage_path)
                img_data = blob.download_as_bytes()
                if storage_path.endswith(".jxl"):
                    img_data = reconstruct_jpeg_from_jxl(img_data)
                elif ".png" in storage_path.lower():
                    ext = ".png"
                return (event_id, img_data, ext)
            except Exception as e:
                logger.debug(f"Storage API download failed for {event_id}, falling back to HTTP: {e}")

        # Try to extract storage path from URL
        if not img_data and url:
            extracted_path = extract_storage_path_from_url(url)
            if extracted_path and bucket:
                try:
                    blob = bucket.blob(extracted_path)
                    img_data = blob.download_as_bytes()
                    if extracted_path.endswith(".jxl"):
                        img_data = reconstruct_jpeg_from_jxl(img_data)
                    elif ".png" in extracted_path.lower():
                        ext = ".png"
                    return (event_id, img_data, ext)
                except Exception as e:
                    logger.debug(f"Storage API (extracted path) failed for {event_id}: {e}")

        # Fallback to HTTP download with shared session.
        # Proxy URLs are excluded: they sit behind the Dartmouth IP whitelist,
        # which Cloud Run's own egress is not part of — the request would 403.
        if not img_data and url and url.startswith("http") and "/api/screenshot-view" not in url:
            response = session.get(url, timeout=30)
            if response.status_code == 200:
                img_data = response.content
                if ".png" in url.lower():
                    ext = ".png"
                elif response.headers.get("content-type", "").startswith("image/png"):
                    ext = ".png"

    except Exception as e:
        logger.warning(f"Failed to download screenshot {event_id}: {e}")

    return (event_id, img_data, ext)


def download_screenshots_concurrent(
    screenshot_infos: List[Dict[str, Any]],
    max_workers: int = 10
) -> List[Tuple[str, bytes, str, str]]:
    """
    Download multiple screenshots concurrently.
    Returns list of (event_id, image_bytes, extension, timestamp_str) tuples.
    """
    results = []
    bucket = None
    try:
        bucket = get_storage_bucket()
    except Exception as e:
        logger.warning(f"Could not get storage bucket: {e}")

    session = get_download_session()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_info = {
            executor.submit(download_single_screenshot, ss_info, bucket, session): ss_info
            for ss_info in screenshot_infos
        }

        for future in as_completed(future_to_info):
            ss_info = future_to_info[future]
            try:
                event_id, img_data, ext = future.result()
                if img_data:
                    # Format timestamp for filename
                    ts_val = ss_info.get("timestamp")
                    if ts_val:
                        if hasattr(ts_val, 'isoformat'):
                            ts_str = ts_val.isoformat().replace(":", "-").replace("T", "_")[:19]
                        else:
                            ts_str = str(ts_val).replace(":", "-").replace("T", "_")[:19]
                    else:
                        ts_str = f"img_{event_id[:8]}"
                    results.append((event_id, img_data, ext, ts_str))
            except Exception as e:
                logger.warning(f"Error processing screenshot download: {e}")

    return results


# ============================================================================
# Screenshot Display Proxy
# Serves JXL-stored screenshots as standard JPEGs so every browser (Chrome
# included) renders them exactly as before. Auth: the object's own Firebase
# download token must be supplied (same capability model as direct download
# URLs), and the endpoint sits behind the Dartmouth IP whitelist.
# ============================================================================

@app.get("/api/screenshot-view")
def screenshot_view(path: str = Query(...), token: str = Query(...)):
    """Serve a stored screenshot (JXL or JPEG) as image/jpeg for display."""
    if not path.startswith("screenshots/") or ".." in path:
        raise HTTPException(status_code=400, detail="Invalid path")

    try:
        bucket = get_storage_bucket()
        blob = bucket.get_blob(path)
        if blob is None:
            raise HTTPException(status_code=404, detail="Not found")

        stored_token = (blob.metadata or {}).get("firebaseStorageDownloadTokens", "")
        if not stored_token or token not in stored_token.split(","):
            raise HTTPException(status_code=403, detail="Invalid token")

        data = blob.download_as_bytes()
        if path.endswith(".jxl"):
            data = reconstruct_jpeg_from_jxl(data)

        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ScreenshotView] Failed for {path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to load screenshot")


# Export Jobs Collection for async exports
EXPORT_JOBS_COLLECTION = config.col("export_jobs")


def run_background_export(job_id: str, participant_id: str, export_level: int,
                          start_date: Optional[str], end_date: Optional[str],
                          user_email: str):
    """Background thread function to run export and update job status.

    Optimizations:
    - Uses concurrent downloads (ThreadPoolExecutor) for screenshots
    - Uses ZIP_STORED for images (already compressed, no benefit from deflate)
    - Uses Storage API directly when possible (faster than HTTP)
    - Reduces Firestore update frequency (every 25% progress)
    """
    job_ref = db.collection(EXPORT_JOBS_COLLECTION).document(job_id)

    try:
        job_ref.update({"status": "processing", "startedAt": datetime.utcnow()})

        # Get participant data
        participant_data = get_participant_data(participant_id)
        participant_ref = get_participant_ref(participant_id)

        if not participant_data:
            events_check = list(participant_ref.collection("events").limit(1).stream())
            if not events_check:
                job_ref.update({
                    "status": "failed",
                    "error": "Participant not found",
                    "completedAt": datetime.utcnow(),
                })
                return

        export_id = job_id
        export_path = EXPORT_DIR / f"{export_id}.zip"

        # Use ZIP_DEFLATED for text, but we'll use ZIP_STORED for images
        with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Export participant metadata
            if participant_data:
                zf.writestr("participant_metadata.json", json.dumps(participant_data, indent=2, default=str))

            # Export EMA responses
            try:
                checkins_ref = participant_ref.collection("ema_responses")
                checkins_data = []
                for checkin_doc in checkins_ref.stream():
                    checkin = checkin_doc.to_dict()
                    for ts_field in ["completedAt", "startedAt", "syncedAt"]:
                        ts_val = checkin.get(ts_field)
                        if ts_val and hasattr(ts_val, 'timestamp'):
                            checkin[ts_field] = datetime.fromtimestamp(ts_val.timestamp()).isoformat()
                    responses = checkin.get("responses", {})
                    if isinstance(responses, str):
                        try:
                            checkin["responses"] = json.loads(responses)
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                    checkins_data.append({"id": checkin_doc.id, **checkin})
                if checkins_data:
                    zf.writestr("ema_responses.json", json.dumps(checkins_data, indent=2, default=str))
            except Exception as e:
                logger.warning(f"Error exporting EMA: {e}")

            # Export safety alerts
            try:
                alerts_ref = participant_ref.collection("safety_alerts")
                alerts_data = []
                for alert_doc in alerts_ref.stream():
                    alert = alert_doc.to_dict()
                    for ts_field in ["triggeredAt", "syncedAt"]:
                        ts_val = alert.get(ts_field)
                        if ts_val and hasattr(ts_val, 'timestamp'):
                            alert[ts_field] = datetime.fromtimestamp(ts_val.timestamp()).isoformat()
                    alerts_data.append({"id": alert_doc.id, **alert})
                if alerts_data:
                    zf.writestr("safety_alerts.json", json.dumps(alerts_data, indent=2, default=str))
            except Exception as e:
                logger.debug(f"Silently handled exception in safety alert export: {e}")

            # Export notification log (bundled with EMA data at Level 1)
            try:
                notif_ref = participant_ref.collection("notification_log")
                notif_data = []
                for notif_doc in notif_ref.order_by("timestamp").stream():
                    notif = notif_doc.to_dict()
                    for ts_field in ["timestamp"]:
                        ts_val = notif.get(ts_field)
                        if ts_val and hasattr(ts_val, 'timestamp'):
                            notif[ts_field] = datetime.fromtimestamp(ts_val.timestamp()).isoformat()
                    notif_data.append({"id": notif_doc.id, **notif})
                if notif_data:
                    zf.writestr("notification_log.json", json.dumps(notif_data, indent=2, default=str))
            except Exception as e:
                logger.debug(f"Error exporting notification log: {e}")

            # Level 2+: Export events
            if export_level >= 2:
                events_ref = participant_ref.collection("events")
                content_start_dt = None
                content_end_dt = None
                if start_date and end_date:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                    content_start_dt, content_end_dt = start_dt, end_dt
                    events_query = events_ref.where("timestamp", ">=", start_dt).where("timestamp", "<", end_dt)
                else:
                    events_query = events_ref

                events_data = []
                screenshot_infos = []

                for event_doc in events_query.stream():
                    event = event_doc.to_dict()
                    for ts_field in ["timestamp", "capturedAt", "createdAt", "syncedAt"]:
                        ts_val = event.get(ts_field)
                        if ts_val and hasattr(ts_val, 'timestamp'):
                            event[ts_field] = datetime.fromtimestamp(ts_val.timestamp()).isoformat()

                    if export_level >= 3:
                        screenshot_url = event.get("screenshotUrl")
                        if screenshot_url:
                            screenshot_infos.append({
                                "event_id": event_doc.id,
                                "url": screenshot_url,
                                "storagePath": event.get("screenshotStoragePath"),  # Direct path if available
                                "timestamp": event.get("timestamp"),
                            })

                    events_data.append({"id": event_doc.id, **event})

                # Merge offloaded content events (content_visible/content_exposure)
                # that now live in Cloud Storage instead of Firestore.
                merge_content_events(events_data, participant_id, content_start_dt, content_end_dt)

                if events_data:
                    zf.writestr("events.json", json.dumps(events_data, indent=2, default=str))

                # Level 3: Download screenshots concurrently
                if export_level >= 3 and screenshot_infos:
                    total = len(screenshot_infos)
                    logger.info(f"Downloading {total} screenshots concurrently for export {job_id}")
                    job_ref.update({"screenshotTotal": total, "screenshotProgress": 0})

                    # Download all screenshots concurrently
                    downloaded = download_screenshots_concurrent(screenshot_infos, max_workers=15)

                    # Write to zip using ZIP_STORED (images are already compressed)
                    for idx, (event_id, img_data, ext, ts_str) in enumerate(downloaded):
                        filename = f"screenshots/{ts_str}_{event_id[:8]}{ext}"
                        # Use ZIP_STORED for images - they're already compressed
                        zf.writestr(
                            zipfile.ZipInfo(filename),
                            img_data,
                            compress_type=zipfile.ZIP_STORED
                        )

                        # Update progress at 25%, 50%, 75%, and 100%
                        progress_pct = (idx + 1) / len(downloaded)
                        if progress_pct >= 0.25 and idx == int(len(downloaded) * 0.25):
                            job_ref.update({"screenshotProgress": int(total * 0.25)})
                        elif progress_pct >= 0.50 and idx == int(len(downloaded) * 0.50):
                            job_ref.update({"screenshotProgress": int(total * 0.50)})
                        elif progress_pct >= 0.75 and idx == int(len(downloaded) * 0.75):
                            job_ref.update({"screenshotProgress": int(total * 0.75)})

                    job_ref.update({"screenshotProgress": total})
                    logger.info(f"Downloaded {len(downloaded)}/{total} screenshots for export {job_id}")

        # Generate filename and store result
        level_names = {1: "meta", 2: "ocr", 3: "full"}
        filename = f"socialscope_export_{participant_id}_L{export_level}_{level_names.get(export_level, 'meta')}"
        if start_date and end_date:
            filename += f"_{start_date}_to_{end_date}"
        filename += ".zip"

        # Upload to Firebase Storage for persistent storage
        try:
            bucket = get_storage_bucket()
            storage_path = f"exports/{participant_id}/{export_id}.zip"
            blob = bucket.blob(storage_path)
            logger.info(f"[Export] Uploading {export_path} to gs://{bucket.name}/{storage_path}")
            blob.upload_from_filename(str(export_path))
            logger.info(f"[Export] Upload complete, generating signed URL")

            # Generate signed URL valid for 7 days
            # Include Content-Disposition header to force download in browser
            # Use IAM-based signing (Cloud Run doesn't have private keys)
            sa_email, access_token = get_signing_credentials()
            download_url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(days=7),
                method="GET",
                response_disposition=f'attachment; filename="{filename}"',
                service_account_email=sa_email,
                access_token=access_token
            )
            logger.info(f"[Export] Successfully uploaded to Firebase Storage: {storage_path}")
        except Exception as upload_err:
            logger.error(f"[Export] FAILED to upload to Storage: {upload_err}", exc_info=True)
            # Don't fall back to unreliable local URLs - surface the error
            raise Exception(f"Storage upload failed: {upload_err}")

        EXPORT_INDEX[export_id] = {
            "filename": filename,
            "created_at": datetime.now().timestamp()
        }

        job_ref.update({
            "status": "completed",
            "downloadUrl": download_url,
            "filename": filename,
            "completedAt": datetime.utcnow(),
        })

        logger.info(f"Background export completed: {job_id}")

    except Exception as e:
        logger.error(f"Background export failed: {e}", exc_info=True)
        job_ref.update({
            "status": "failed",
            "error": str(e),
            "completedAt": datetime.utcnow(),
        })


@app.get("/api/export/estimate")
@limiter.limit("30/minute")
def estimate_export(
    request: Request,
    participant_id: str = Query(...),
    export_level: int = Query(1, ge=1, le=3, description="1=Meta+EMA, 2=+OCR/Events, 3=+Screenshots"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user: dict = Depends(verify_firebase_token),
):
    """
    Estimate export size and time.
    Level 1: Metadata + EMA responses + Safety alerts (~10-50 KB)
    Level 2: Level 1 + All events with OCR data (~100 KB - 5 MB)
    Level 3: Level 2 + Screenshot images (~10 MB - 500 MB+)
    """
    try:
        participant_ref = get_participant_ref(participant_id)

        # Count events
        events_ref = participant_ref.collection("events")
        if start_date and end_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            events_query = events_ref.where("timestamp", ">=", start_dt).where("timestamp", "<", end_dt)
        else:
            events_query = events_ref

        # Get event count and screenshot URLs
        events = list(events_query.stream())
        event_count = len(events)
        screenshot_count = 0
        total_screenshot_size = 0

        for event_doc in events:
            event = event_doc.to_dict()
            if event.get("eventType") == "screenshot" or event.get("type") == "screenshot":
                screenshot_count += 1
                # Estimate ~60KB per screenshot (750px width, JPEG quality 70)
                total_screenshot_size += 60 * 1024

        # Count EMAs and alerts
        ema_count = len(list(participant_ref.collection("ema_responses").limit(500).stream()))
        alert_count = len(list(participant_ref.collection("safety_alerts").limit(100).stream()))

        # Calculate estimated sizes
        level1_size = 10 * 1024 + (ema_count * 500) + (alert_count * 300)  # ~10KB base + EMA + alerts
        level2_size = level1_size + (event_count * 2000)  # ~2KB per event with OCR
        level3_size = level2_size + total_screenshot_size

        # Estimate time (rough: 1MB per second for downloads)
        level1_time = max(1, level1_size / (1024 * 1024))
        level2_time = max(2, level2_size / (1024 * 1024))
        level3_time = max(5, level3_size / (500 * 1024))  # Screenshots are slower

        # Determine if email notification should be offered
        needs_background = level3_size > 10 * 1024 * 1024  # > 10MB

        return {
            "participant_id": participant_id,
            "event_count": event_count,
            "screenshot_count": screenshot_count,
            "ema_count": ema_count,
            "alert_count": alert_count,
            "estimates": {
                "level1": {
                    "name": "Metadata + EMA + Alerts",
                    "size_bytes": level1_size,
                    "size_display": f"{level1_size / 1024:.1f} KB",
                    "time_seconds": int(level1_time),
                    "time_display": f"~{int(level1_time)} sec",
                },
                "level2": {
                    "name": "Level 1 + Events + OCR",
                    "size_bytes": level2_size,
                    "size_display": f"{level2_size / 1024:.1f} KB" if level2_size < 1024*1024 else f"{level2_size / (1024*1024):.1f} MB",
                    "time_seconds": int(level2_time),
                    "time_display": f"~{int(level2_time)} sec",
                },
                "level3": {
                    "name": "Level 2 + Screenshots",
                    "size_bytes": level3_size,
                    "size_display": f"{level3_size / (1024*1024):.1f} MB",
                    "time_seconds": int(level3_time),
                    "time_display": f"~{int(level3_time // 60)} min {int(level3_time % 60)} sec" if level3_time > 60 else f"~{int(level3_time)} sec",
                    "needs_background": needs_background,
                },
            }
        }
    except Exception as e:
        logger.error(f"Failed to estimate export: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class AsyncExportRequest(BaseModel):
    participant_id: str
    export_level: int = 1
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    notify_email: Optional[str] = None


@app.post("/api/export/async")
@limiter.limit("10/minute")
def start_async_export(
    request: Request,
    body: AsyncExportRequest,
    user: dict = Depends(verify_firebase_token),
):
    """
    Start an asynchronous export job for large exports (Level 3 with screenshots).
    Returns immediately with a job ID. Client can poll for status or receive email notification.
    """
    try:
        # Validate participant exists
        participant_data = get_participant_data(body.participant_id)
        participant_ref = get_participant_ref(body.participant_id)

        if not participant_data:
            events_check = list(participant_ref.collection("events").limit(1).stream())
            if not events_check:
                raise HTTPException(status_code=404, detail="Participant not found")

        # Create job document
        job_id = uuid.uuid4().hex
        job_ref = db.collection(EXPORT_JOBS_COLLECTION).document(job_id)

        user_email = body.notify_email or user.get("email")

        job_ref.set({
            "jobId": job_id,
            "participantId": body.participant_id,
            "exportLevel": body.export_level,
            "startDate": body.start_date,
            "endDate": body.end_date,
            "status": "pending",
            "createdAt": datetime.utcnow(),
            "createdBy": user.get("email"),
            "notifyEmail": user_email,
        })

        # Start background thread
        thread = threading.Thread(
            target=run_background_export,
            args=(job_id, body.participant_id, body.export_level,
                  body.start_date, body.end_date, user_email),
            daemon=True
        )
        thread.start()

        return {
            "jobId": job_id,
            "status": "pending",
            "message": "Export started. Check 'My Exports' for status.",
            "statusUrl": f"/api/export/jobs/{job_id}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start async export: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export/jobs")
@limiter.limit("60/minute")
def get_user_export_jobs(request: Request, user: dict = Depends(verify_firebase_token)):
    """Get all export jobs for the current user."""
    try:
        user_email = user.get("email")
        jobs_ref = db.collection(EXPORT_JOBS_COLLECTION)

        # Query jobs created by this user, ordered by creation time
        jobs_query = jobs_ref.where("createdBy", "==", user_email).order_by("createdAt", direction=firestore.Query.DESCENDING).limit(20)

        jobs = []
        for job_doc in jobs_query.stream():
            job_data = job_doc.to_dict()

            # Convert timestamps
            for ts_field in ["createdAt", "startedAt", "completedAt"]:
                if job_data.get(ts_field) and hasattr(job_data[ts_field], 'timestamp'):
                    job_data[ts_field] = datetime.fromtimestamp(job_data[ts_field].timestamp()).isoformat() + "Z"

            # Calculate time estimate based on export level and screenshot count
            if job_data.get("status") == "processing":
                total = job_data.get("screenshotTotal", 0)
                progress = job_data.get("screenshotProgress", 0)
                if total > 0 and progress > 0:
                    # Estimate ~2 seconds per screenshot
                    remaining = total - progress
                    est_seconds = remaining * 2
                    if est_seconds > 60:
                        job_data["timeEstimate"] = f"~{est_seconds // 60} min remaining"
                    else:
                        job_data["timeEstimate"] = f"~{est_seconds} sec remaining"
                else:
                    job_data["timeEstimate"] = "Calculating..."

            jobs.append(job_data)

        return {"jobs": jobs}

    except Exception as e:
        logger.error(f"Failed to get user export jobs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export/jobs/{job_id}")
@limiter.limit("120/minute")
def get_export_job_status(
    request: Request,
    job_id: str,
    user: dict = Depends(verify_firebase_token),
):
    """Get the status of an export job."""
    try:
        job_ref = db.collection(EXPORT_JOBS_COLLECTION).document(job_id)
        job_doc = job_ref.get()

        if not job_doc.exists:
            raise HTTPException(status_code=404, detail="Export job not found")

        job_data = job_doc.to_dict()

        # Convert timestamps
        for ts_field in ["createdAt", "startedAt", "completedAt"]:
            if job_data.get(ts_field) and hasattr(job_data[ts_field], 'timestamp'):
                job_data[ts_field] = datetime.fromtimestamp(job_data[ts_field].timestamp()).isoformat() + "Z"

        return job_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get export job status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/export/jobs/{job_id}")
@limiter.limit("30/minute")
def cancel_export_job(
    request: Request,
    job_id: str,
    user: dict = Depends(verify_firebase_token),
):
    """Cancel a pending or processing export job."""
    try:
        job_ref = db.collection(EXPORT_JOBS_COLLECTION).document(job_id)
        job_doc = job_ref.get()

        if not job_doc.exists:
            raise HTTPException(status_code=404, detail="Export job not found")

        job_data = job_doc.to_dict()

        # Only allow cancellation of pending or processing jobs
        if job_data.get("status") not in ["pending", "processing"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job with status: {job_data.get('status')}"
            )

        # Update job status to cancelled
        job_ref.update({
            "status": "cancelled",
            "cancelledAt": datetime.utcnow(),
            "cancelledBy": user.get("email", "unknown")
        })

        logger.info(f"Export job {job_id} cancelled by {user.get('email')}")

        return {"message": "Export job cancelled", "job_id": job_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel export job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export")
@limiter.limit("5/minute")
def export_participant_data(
    request: Request,
    participant_id: str = Query(...),
    export_level: int = Query(1, ge=1, le=3, description="1=Meta+EMA, 2=+Events/OCR, 3=+Screenshots"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user: dict = Depends(verify_firebase_token),
):
    """
    Export data for a participant as a ZIP file.
    Level 1: Metadata + EMA responses + Safety alerts
    Level 2: Level 1 + All events with OCR data
    Level 3: Level 2 + Screenshot images from Firebase Storage

    Optimizations:
    - Uses concurrent downloads for screenshots
    - Uses ZIP_STORED for images (already compressed)
    - Uploads to Firebase Storage for persistent download links
    """
    try:
        # Check participant exists in either collection
        participant_data = get_participant_data(participant_id)

        # Get reference for subcollections (always under participants/{id})
        participant_ref = get_participant_ref(participant_id)

        # Verify participant exists (in either collection or has data)
        if not participant_data:
            # Check if there's any data for this participant
            events_check = list(participant_ref.collection("events").limit(1).stream())
            alerts_check = list(participant_ref.collection("safety_alerts").limit(1).stream())
            ema_check = list(participant_ref.collection("ema_responses").limit(1).stream())
            if not events_check and not alerts_check and not ema_check:
                raise HTTPException(status_code=404, detail="Participant not found")

        export_id = uuid.uuid4().hex
        export_path = EXPORT_DIR / f"{export_id}.zip"

        with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Export participant metadata (all levels)
            if participant_data:
                zf.writestr("participant_metadata.json", json.dumps(participant_data, indent=2, default=str))

            # Export check-ins/EMA responses (all levels)
            try:
                checkins_ref = participant_ref.collection("ema_responses")
                checkins_data = []
                for checkin_doc in checkins_ref.stream():
                    checkin = checkin_doc.to_dict()
                    for ts_field in ["completedAt", "startedAt", "syncedAt"]:
                        ts_val = checkin.get(ts_field)
                        if ts_val and hasattr(ts_val, 'timestamp'):
                            checkin[ts_field] = datetime.fromtimestamp(ts_val.timestamp()).isoformat()
                    responses = checkin.get("responses", {})
                    if isinstance(responses, str):
                        try:
                            checkin["responses"] = json.loads(responses)
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                    checkins_data.append({"id": checkin_doc.id, **checkin})

                if checkins_data:
                    zf.writestr("ema_responses.json", json.dumps(checkins_data, indent=2, default=str))
            except Exception as e:
                logger.warning(f"Error exporting EMA responses: {e}")

            # Export safety alerts (all levels)
            try:
                alerts_ref = participant_ref.collection("safety_alerts")
                alerts_data = []
                for alert_doc in alerts_ref.stream():
                    alert = alert_doc.to_dict()
                    for ts_field in ["triggeredAt", "syncedAt"]:
                        ts_val = alert.get(ts_field)
                        if ts_val and hasattr(ts_val, 'timestamp'):
                            alert[ts_field] = datetime.fromtimestamp(ts_val.timestamp()).isoformat()
                    alerts_data.append({"id": alert_doc.id, **alert})

                if alerts_data:
                    zf.writestr("safety_alerts.json", json.dumps(alerts_data, indent=2, default=str))
            except Exception as e:
                logger.debug(f"Silently handled exception in safety alert export: {e}")

            # Export notification log (bundled with EMA data at Level 1)
            try:
                notif_ref = participant_ref.collection("notification_log")
                notif_data = []
                for notif_doc in notif_ref.order_by("timestamp").stream():
                    notif = notif_doc.to_dict()
                    for ts_field in ["timestamp"]:
                        ts_val = notif.get(ts_field)
                        if ts_val and hasattr(ts_val, 'timestamp'):
                            notif[ts_field] = datetime.fromtimestamp(ts_val.timestamp()).isoformat()
                    notif_data.append({"id": notif_doc.id, **notif})
                if notif_data:
                    zf.writestr("notification_log.json", json.dumps(notif_data, indent=2, default=str))
            except Exception as e:
                logger.debug(f"Error exporting notification log: {e}")

            # Level 2+: Export events with OCR data
            if export_level >= 2:
                events_ref = participant_ref.collection("events")
                content_start_dt = None
                content_end_dt = None

                if start_date and end_date:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                    content_start_dt, content_end_dt = start_dt, end_dt
                    events_query = events_ref.where(
                        "timestamp", ">=", start_dt
                    ).where(
                        "timestamp", "<", end_dt
                    ).order_by("timestamp")
                else:
                    events_query = events_ref.order_by("timestamp")

                events_data = []
                screenshot_infos = []  # For level 3

                for event_doc in events_query.stream():
                    event = event_doc.to_dict()
                    for ts_field in ["timestamp", "capturedAt", "createdAt", "syncedAt"]:
                        ts_val = event.get(ts_field)
                        if ts_val and hasattr(ts_val, 'timestamp'):
                            event[ts_field] = datetime.fromtimestamp(ts_val.timestamp()).isoformat()

                    # Collect screenshot info for level 3
                    if export_level >= 3:
                        screenshot_url = event.get("screenshotUrl")
                        if screenshot_url:
                            screenshot_infos.append({
                                "event_id": event_doc.id,
                                "url": screenshot_url,
                                "storagePath": event.get("screenshotStoragePath"),
                                "timestamp": event.get("timestamp"),
                            })

                    events_data.append({"id": event_doc.id, **event})

                # Merge offloaded content events now stored in Cloud Storage.
                merge_content_events(events_data, participant_id, content_start_dt, content_end_dt)

                if events_data:
                    zf.writestr("events.json", json.dumps(events_data, indent=2, default=str))

                # Level 3: Download screenshots concurrently
                if export_level >= 3 and screenshot_infos:
                    logger.info(f"Downloading {len(screenshot_infos)} screenshots concurrently for sync export")

                    # Download all screenshots concurrently
                    downloaded = download_screenshots_concurrent(screenshot_infos, max_workers=15)

                    # Write to zip using ZIP_STORED (images are already compressed)
                    for event_id, img_data, ext, ts_str in downloaded:
                        filename = f"screenshots/{ts_str}_{event_id[:8]}{ext}"
                        zf.writestr(
                            zipfile.ZipInfo(filename),
                            img_data,
                            compress_type=zipfile.ZIP_STORED
                        )

                    logger.info(f"Downloaded {len(downloaded)}/{len(screenshot_infos)} screenshots for sync export")

        level_names = {1: "meta", 2: "ocr", 3: "full"}
        filename = f"socialscope_export_{participant_id}_L{export_level}_{level_names.get(export_level, 'meta')}"
        if start_date and end_date:
            filename += f"_{start_date}_to_{end_date}"
        filename += ".zip"

        # Upload to Firebase Storage for persistent download link
        download_url = f"/api/exports/{export_id}"
        try:
            bucket = get_storage_bucket()
            storage_path = f"exports/{participant_id}/{export_id}.zip"
            blob = bucket.blob(storage_path)
            logger.info(f"[SyncExport] Uploading {export_path} to gs://{bucket.name}/{storage_path}")
            blob.upload_from_filename(str(export_path))
            logger.info(f"[SyncExport] Upload complete, generating signed URL")

            # Generate signed URL valid for 7 days
            # Include Content-Disposition header to force download in browser
            # Use IAM-based signing (Cloud Run doesn't have private keys)
            sa_email, access_token = get_signing_credentials()
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(days=7),
                method="GET",
                response_disposition=f'attachment; filename="{filename}"',
                service_account_email=sa_email,
                access_token=access_token
            )
            download_url = signed_url
            logger.info(f"[SyncExport] Successfully uploaded to Firebase Storage: {storage_path}")
        except Exception as upload_err:
            logger.error(f"[SyncExport] FAILED to upload to Storage: {upload_err}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Storage upload failed: {upload_err}")

        EXPORT_INDEX[export_id] = {
            "filename": filename,
            "created_at": datetime.now().timestamp(),
            "download_url": download_url,
        }

        return {
            "download_url": download_url,
            "filename": filename
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/exports/{export_id}")
@limiter.limit("30/minute")
def download_export(request: Request, export_id: str, user: dict = Depends(verify_firebase_token)):
    """Download an export file (authenticated — serves participant PHI).

    First tries local file, then checks EXPORT_INDEX for a stored signed URL,
    then checks Firestore export_jobs for async export URLs.
    """
    is_admin = user.get("dashboard_role") == "admin"

    # Reject any non-canonical id before it touches the filesystem path below
    # (path-traversal guard — export ids are always uuid4 hex).
    if not is_valid_export_id(export_id):
        raise HTTPException(status_code=400, detail="Invalid export id")

    export_path = EXPORT_DIR / f"{export_id}.zip"

    # Try local file first
    if export_path.exists():
        meta = EXPORT_INDEX.get(export_id, {})
        filename = meta.get("filename", f"{export_id}.zip")
        return FileResponse(
            export_path,
            media_type="application/zip",
            filename=filename
        )

    # Check if we have a stored signed URL in memory
    meta = EXPORT_INDEX.get(export_id, {})
    if meta.get("download_url") and meta["download_url"].startswith("http"):
        return RedirectResponse(url=meta["download_url"])

    # Check Firestore for async export jobs
    try:
        job_ref = db.collection(EXPORT_JOBS_COLLECTION).document(export_id)
        job_doc = job_ref.get()
        if job_doc.exists:
            job_data = job_doc.to_dict()
            # Ownership: a job's PHI is downloadable by its creator or an admin
            owner = job_data.get("createdBy")
            if owner and owner != user.get("email") and not is_admin:
                raise HTTPException(status_code=403, detail="Not authorized to download this export")
            download_url = job_data.get("downloadUrl")
            if download_url and download_url.startswith("http"):
                return RedirectResponse(url=download_url)
    except HTTPException:
        raise  # don't let the ownership 403 fall through to a 404
    except Exception as e:
        logger.warning(f"Error checking Firestore for export {export_id}: {e}")

    raise HTTPException(status_code=404, detail="Export not found or expired")


# ============================================================================
# Admin User Management Endpoints
# ============================================================================

class AddUserRequest(BaseModel):
    email: str
    role: str = "user"


class UpdateUserRequest(BaseModel):
    role: str


@app.get("/api/admin/users")
@limiter.limit("30/minute")
def get_all_users(request: Request, user: dict = Depends(verify_admin_token)):
    """Get list of all authorized dashboard users (admin only)."""
    try:
        users_ref = db.collection(DASHBOARD_USERS_COLLECTION)
        users = []

        for user_doc in users_ref.stream():
            user_data = user_doc.to_dict()
            users.append({
                "email": user_doc.id,
                "role": user_data.get("role", "user"),
                "addedAt": user_data.get("addedAt").isoformat() if user_data.get("addedAt") else None,
                "addedBy": user_data.get("addedBy"),
            })

        return {"users": sorted(users, key=lambda x: x["email"])}
    except Exception as e:
        logger.error(f"Failed to get users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/users")
@limiter.limit("20/minute")
def add_user(request: Request, body: AddUserRequest, user: dict = Depends(verify_admin_token)):
    """Add a new authorized user (admin only)."""
    try:
        email = body.email.lower().strip()
        role = body.role.lower()

        if role not in ("user", "admin"):
            raise HTTPException(status_code=400, detail="Role must be 'user' or 'admin'")

        # Check if user already exists
        user_ref = db.collection(DASHBOARD_USERS_COLLECTION).document(email)
        if user_ref.get().exists:
            raise HTTPException(status_code=400, detail="User already exists")

        # Add user
        user_ref.set({
            "email": email,
            "role": role,
            "addedAt": datetime.utcnow(),
            "addedBy": user.get("email"),
        })

        logger.info(f"User {email} added with role {role} by {user.get('email')}")
        return {"message": f"User {email} added successfully", "email": email, "role": role}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/admin/users/{email}")
@limiter.limit("20/minute")
def update_user_role(request: Request, email: str, body: UpdateUserRequest, user: dict = Depends(verify_admin_token)):
    """Update a user's role (admin only)."""
    try:
        email = email.lower().strip()
        role = body.role.lower()

        if role not in ("user", "admin"):
            raise HTTPException(status_code=400, detail="Role must be 'user' or 'admin'")

        # Check if user exists
        user_ref = db.collection(DASHBOARD_USERS_COLLECTION).document(email)
        if not user_ref.get().exists:
            raise HTTPException(status_code=404, detail="User not found")

        # Prevent admin from demoting themselves
        if email == user.get("email", "").lower() and role != "admin":
            raise HTTPException(status_code=400, detail="Cannot demote yourself from admin")

        # Update role
        user_ref.update({
            "role": role,
            "updatedAt": datetime.utcnow(),
            "updatedBy": user.get("email"),
        })

        logger.info(f"User {email} role updated to {role} by {user.get('email')}")
        return {"message": f"User {email} role updated to {role}", "email": email, "role": role}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/users/{email}")
@limiter.limit("20/minute")
def remove_user(request: Request, email: str, user: dict = Depends(verify_admin_token)):
    """Remove a user (admin only)."""
    try:
        email = email.lower().strip()

        # Prevent admin from removing themselves
        if email == user.get("email", "").lower():
            raise HTTPException(status_code=400, detail="Cannot remove yourself")

        # Check if user exists
        user_ref = db.collection(DASHBOARD_USERS_COLLECTION).document(email)
        if not user_ref.get().exists:
            raise HTTPException(status_code=404, detail="User not found")

        # Remove user
        user_ref.delete()

        logger.info(f"User {email} removed by {user.get('email')}")
        return {"message": f"User {email} removed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Exports Archive-and-Clear (admin only, multi-confirmation)
#
# Research data retention policy: NOTHING is ever deleted outright. This
# endpoint moves dashboard export artifacts (exports/) from the live bucket
# into the permanent archive backup bucket, and removes each original ONLY
# after its archive copy is verified (size + MD5). Study data (screenshots/,
# html/) is never touched. Every invocation is audit-logged.
# ============================================================================

ARCHIVE_BACKUP_BUCKET = "r01-redditx-suicide-archive-backup"
EXPORTS_ARCHIVE_CONFIRM_TEXT = "ARCHIVE AND CLEAR EXPORTS"


class ArchiveExportsRequest(BaseModel):
    confirm_text: str
    pi_confirmed: bool


@app.post("/api/admin/exports/archive-and-clear")
@limiter.limit("3/hour")
def archive_and_clear_exports(
    request: Request,
    body: ArchiveExportsRequest,
    user: dict = Depends(verify_admin_token),
):
    """
    Move all exports/ artifacts to the archive backup bucket, verifying each
    copy before removing the original. Requires the exact confirmation phrase
    and explicit confirmation with the PI (Nicholas C. Jacobson).
    """
    if body.confirm_text.strip() != EXPORTS_ARCHIVE_CONFIRM_TEXT:
        raise HTTPException(status_code=400, detail="Confirmation text does not match")
    if not body.pi_confirmed:
        raise HTTPException(
            status_code=400,
            detail="This action requires confirmation with the PI (Nicholas C. Jacobson)",
        )

    try:
        from google.cloud import storage as gcs

        client = gcs.Client()
        src_bucket = client.bucket(get_storage_bucket().name)
        dst_bucket = client.bucket(ARCHIVE_BACKUP_BUCKET)

        ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        dest_prefix = f"exports-archived/{ts}/"

        moved, failed, total_bytes = 0, 0, 0
        blobs = list(src_bucket.list_blobs(prefix="exports/"))

        for blob in blobs:
            try:
                copied = src_bucket.copy_blob(blob, dst_bucket, dest_prefix + blob.name)
                # Verify the archive copy byte-for-byte before removing original
                if copied.md5_hash == blob.md5_hash and copied.size == blob.size:
                    blob.delete()
                    moved += 1
                    total_bytes += blob.size or 0
                else:
                    failed += 1
                    logger.error(f"[ExportsArchive] Copy verification FAILED for {blob.name} — original kept")
            except Exception as e:
                failed += 1
                logger.error(f"[ExportsArchive] Failed to archive {blob.name}: {e}")

        # Audit log — required for research data governance
        db.collection(config.col("admin_audit_log")).document().set({
            "action": "exports_archive_and_clear",
            "performedBy": user.get("email"),
            "piConfirmedWith": "Nicholas C. Jacobson",
            "piConfirmed": True,
            "objectsMoved": moved,
            "objectsFailed": failed,
            "bytesMoved": total_bytes,
            "archiveDestination": f"gs://{ARCHIVE_BACKUP_BUCKET}/{dest_prefix}",
            "performedAt": datetime.utcnow(),
        })

        logger.warning(
            f"[ExportsArchive] {user.get('email')} archived {moved} export objects "
            f"({total_bytes:,} bytes) to {dest_prefix}; {failed} failures (originals kept)"
        )

        return {
            "moved": moved,
            "failed": failed,
            "bytesMoved": total_bytes,
            "archiveDestination": f"gs://{ARCHIVE_BACKUP_BUCKET}/{dest_prefix}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ExportsArchive] Operation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Archive operation failed — no data was deleted")


# ============================================================================
# Alert Recipients Management (for Twilio SMS alerts)
# ============================================================================

ALERT_RECIPIENTS_COLLECTION = config.col("alert_recipients")


class AddRecipientRequest(BaseModel):
    phone: str
    name: Optional[str] = None


@app.get("/api/admin/alert-recipients")
@limiter.limit("30/minute")
def get_alert_recipients(request: Request, user: dict = Depends(verify_admin_token)):
    """Get list of safety alert SMS recipients (admin only)."""
    try:
        recipients_ref = db.collection(ALERT_RECIPIENTS_COLLECTION)
        recipients = []

        for doc in recipients_ref.stream():
            data = doc.to_dict()
            recipients.append({
                "phone": doc.id,
                "name": data.get("name"),
                "addedAt": data.get("addedAt").isoformat() if data.get("addedAt") else None,
                "addedBy": data.get("addedBy"),
            })

        return {"recipients": sorted(recipients, key=lambda x: x.get("name") or x["phone"])}
    except Exception as e:
        logger.error(f"Failed to get alert recipients: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/alert-recipients")
@limiter.limit("20/minute")
def add_alert_recipient(request: Request, body: AddRecipientRequest, user: dict = Depends(verify_admin_token)):
    """Add a new safety alert SMS recipient (admin only)."""
    try:
        # Clean phone number (keep only digits)
        phone = ''.join(filter(str.isdigit, body.phone))

        if len(phone) != 10:
            raise HTTPException(status_code=400, detail="Phone must be a 10-digit US number")

        # Check if already exists
        recipient_ref = db.collection(ALERT_RECIPIENTS_COLLECTION).document(phone)
        if recipient_ref.get().exists:
            raise HTTPException(status_code=400, detail="This phone number is already registered")

        # Add recipient
        recipient_ref.set({
            "phone": phone,
            "name": body.name.strip() if body.name else None,
            "addedAt": datetime.utcnow(),
            "addedBy": user.get("email"),
        })

        logger.info(f"Alert recipient {phone} added by {user.get('email')}")
        return {"message": f"Recipient added successfully", "phone": phone}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add alert recipient: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/alert-recipients/{phone}")
@limiter.limit("20/minute")
def remove_alert_recipient(request: Request, phone: str, user: dict = Depends(verify_admin_token)):
    """Remove a safety alert SMS recipient (admin only)."""
    try:
        # Clean phone number
        phone = ''.join(filter(str.isdigit, phone))

        recipient_ref = db.collection(ALERT_RECIPIENTS_COLLECTION).document(phone)
        if not recipient_ref.get().exists:
            raise HTTPException(status_code=404, detail="Recipient not found")

        recipient_ref.delete()

        logger.info(f"Alert recipient {phone} removed by {user.get('email')}")
        return {"message": f"Recipient removed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove alert recipient: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Admin Initialization
# ============================================================================

@app.post("/api/admin/init")
@limiter.limit("5/minute")
def initialize_admin(request: Request):
    """
    Initialize the first admin user. This endpoint only works when no users exist.
    Used for initial setup only.
    """
    try:
        users_ref = db.collection(DASHBOARD_USERS_COLLECTION)
        existing_users = list(users_ref.limit(1).stream())

        if existing_users:
            raise HTTPException(
                status_code=400,
                detail="Admin initialization already completed. Use the user management page to add users."
            )

        # Create initial admin
        initial_admin_email = "nicholas.c.jacobson@dartmouth.edu"
        user_ref = users_ref.document(initial_admin_email)
        user_ref.set({
            "email": initial_admin_email,
            "role": "admin",
            "addedAt": datetime.utcnow(),
            "addedBy": "system_init",
        })

        logger.info(f"Initial admin {initial_admin_email} created via system init")
        return {
            "message": "Admin initialized successfully",
            "admin_email": initial_admin_email
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initialize admin: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# On-Call Roster & Escalation System
# ============================================================================

ONCALL_COLLECTION = config.col("oncall_roster")
SAFETY_EVENTS_COLLECTION = config.col("safety_events")
FOLLOWUP_COLLECTION = config.col("followup_schedule")

# Escalation timing (in minutes)
ESCALATION_PRIMARY_TIMEOUT = 15  # Primary on-call has 15 min to respond
ESCALATION_BACKUP_TIMEOUT = 15   # Backup has 15 min before PI is paged


class OnCallUpdate(BaseModel):
    role: str  # "primary", "backup", "pi"
    name: str
    email: str
    phone: Optional[str] = None


class DispositionLog(BaseModel):
    safety_event_id: str
    disposition: str  # "contacted_safe", "contacted_needs_support", "unable_to_reach", "false_alarm", "escalated_988", "escalated_er"
    notes: Optional[str] = None
    outreach_method: Optional[str] = None  # "phone_call", "sms", "in_person"
    participant_response: Optional[str] = None


class FollowUpLog(BaseModel):
    followup_id: str
    status: str  # "completed", "unable_to_reach", "rescheduled", "cancelled"
    notes: Optional[str] = None
    outreach_method: Optional[str] = None


@app.get("/api/oncall/roster")
@limiter.limit("30/minute")
def get_oncall_roster(request: Request, user: dict = Depends(verify_firebase_token)):
    """Get the current on-call roster."""
    try:
        roster = {}
        for doc in db.collection(ONCALL_COLLECTION).stream():
            data = doc.to_dict()
            roster[doc.id] = {
                "role": doc.id,
                "name": data.get("name"),
                "email": data.get("email"),
                "phone": data.get("phone"),
                "updatedAt": data.get("updatedAt").isoformat() if data.get("updatedAt") else None,
                "updatedBy": data.get("updatedBy"),
            }
        return {"roster": roster}
    except Exception as e:
        logger.error(f"Failed to get on-call roster: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/oncall/roster")
@limiter.limit("20/minute")
def update_oncall_roster(request: Request, body: OnCallUpdate, user: dict = Depends(verify_admin_token)):
    """Update an on-call roster position (admin only)."""
    try:
        if body.role not in ("primary", "backup", "pi"):
            raise HTTPException(status_code=400, detail="Role must be primary, backup, or pi")

        db.collection(ONCALL_COLLECTION).document(body.role).set({
            "name": body.name,
            "email": body.email,
            "phone": body.phone,
            "updatedAt": datetime.utcnow(),
            "updatedBy": user.get("email"),
        })

        logger.info(f"On-call roster updated: {body.role} = {body.name} by {user.get('email')}")
        return {"message": f"On-call {body.role} updated to {body.name}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update on-call roster: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Safety Event Audit Trail & Disposition Logging
# ============================================================================

@app.post("/api/safety-events/{event_id}/disposition")
@limiter.limit("30/minute")
def log_disposition(
    request: Request,
    event_id: str,
    body: DispositionLog,
    user: dict = Depends(verify_firebase_token),
):
    """
    Log a disposition for a safety event (any team member).
    This is the primary way on-call staff acknowledge and document their response.
    Stops escalation timer when logged.
    """
    try:
        event_ref = db.collection(SAFETY_EVENTS_COLLECTION).document(event_id)
        event_doc = event_ref.get()

        if not event_doc.exists:
            # Create the safety event document if it doesn't exist yet
            event_ref.set({
                "createdAt": datetime.utcnow(),
                "source": "manual",
            })

        # Add disposition to the audit trail
        disposition_id = str(uuid.uuid4())
        event_ref.collection("audit_trail").document(disposition_id).set({
            "type": "disposition",
            "disposition": body.disposition,
            "notes": body.notes,
            "outreachMethod": body.outreach_method,
            "participantResponse": body.participant_response,
            "loggedBy": user.get("email"),
            "loggedAt": datetime.utcnow(),
        })

        # Update the event's status. "acknowledged"/"ongoing" are NOT terminal —
        # they mark that on-call has taken it (stops paging via the acknowledged
        # flag) but leave the event open so the scheduler keeps nudging for a
        # final disposition. Only a final disposition stops escalation outright.
        status_update = {
            "currentDisposition": body.disposition,
            "lastRespondedBy": user.get("email"),
            "lastRespondedAt": datetime.utcnow(),
        }
        if body.disposition in ("acknowledged", "ongoing"):
            status_update["acknowledged"] = True
            status_update["acknowledgedBy"] = user.get("email")
            status_update["acknowledgedAt"] = datetime.utcnow()
            if body.disposition == "ongoing":
                status_update["lastCheckInAt"] = datetime.utcnow()
            # Don't set currentDisposition to "acknowledged" (not a real outcome) —
            # keep it null/ongoing so the disposition-needed reminder keeps firing.
            if body.disposition == "acknowledged":
                status_update.pop("currentDisposition")
        else:
            status_update["escalationStopped"] = True
        event_ref.update(status_update)

        # Calculate time-to-human-contact if this is the first disposition
        if not event_doc.exists or not event_doc.to_dict().get("firstResponseAt"):
            created_at = event_doc.to_dict().get("createdAt") if event_doc.exists else datetime.utcnow()
            if created_at and hasattr(created_at, 'timestamp'):
                # createdAt is a UTC Firestore timestamp; utcfromtimestamp keeps the
                # subtraction in UTC (fromtimestamp would shift to local time).
                response_time_seconds = (datetime.utcnow() - datetime.utcfromtimestamp(created_at.timestamp())).total_seconds()
            else:
                response_time_seconds = 0

            event_ref.update({
                "firstResponseAt": datetime.utcnow(),
                "timeToHumanContactSeconds": response_time_seconds,
            })

        logger.info(f"Disposition logged for safety event {event_id}: {body.disposition} by {user.get('email')}")

        # Check if adverse event threshold is met
        adverse_dispositions = ["escalated_988", "escalated_er", "contacted_needs_support"]
        if body.disposition in adverse_dispositions:
            event_ref.update({"adverseEventFlag": True})

        return {
            "message": "Disposition logged",
            "dispositionId": disposition_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to log disposition: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/safety-events/{event_id}/audit-trail")
@limiter.limit("30/minute")
def get_audit_trail(
    request: Request,
    event_id: str,
    user: dict = Depends(verify_firebase_token),
):
    """Get the full audit trail for a safety event."""
    try:
        event_ref = db.collection(SAFETY_EVENTS_COLLECTION).document(event_id)
        event_doc = event_ref.get()

        if not event_doc.exists:
            raise HTTPException(status_code=404, detail="Safety event not found")

        event_data = event_doc.to_dict()

        # Get all audit trail entries
        trail = []
        for doc in event_ref.collection("audit_trail").order_by("loggedAt").stream():
            entry = doc.to_dict()
            entry["id"] = doc.id
            if entry.get("loggedAt") and hasattr(entry["loggedAt"], "isoformat"):
                entry["loggedAt"] = entry["loggedAt"].isoformat()
            elif entry.get("loggedAt") and hasattr(entry["loggedAt"], "timestamp"):
                entry["loggedAt"] = datetime.fromtimestamp(entry["loggedAt"].timestamp()).isoformat()
            trail.append(entry)

        return {
            "eventId": event_id,
            "event": {
                "currentDisposition": event_data.get("currentDisposition"),
                "adverseEventFlag": event_data.get("adverseEventFlag", False),
                "timeToHumanContactSeconds": event_data.get("timeToHumanContactSeconds"),
                "escalationStopped": event_data.get("escalationStopped", False),
                "firstResponseAt": event_data.get("firstResponseAt").isoformat() if event_data.get("firstResponseAt") and hasattr(event_data.get("firstResponseAt"), "isoformat") else None,
            },
            "auditTrail": trail,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get audit trail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/safety-events/active")
@limiter.limit("30/minute")
def get_active_safety_events(request: Request, user: dict = Depends(verify_firebase_token)):
    """Get all active (unresolved) safety events for the dashboard."""
    try:
        events = []
        # Get events that haven't been resolved
        query = db.collection(SAFETY_EVENTS_COLLECTION).order_by(
            "createdAt", direction=firestore.Query.DESCENDING
        ).limit(100)

        for doc in query.stream():
            data = doc.to_dict()
            created_at = data.get("createdAt")
            if created_at and hasattr(created_at, "timestamp"):
                created_at = datetime.fromtimestamp(created_at.timestamp())

            events.append({
                "id": doc.id,
                "participantId": data.get("participantId"),
                "alertType": data.get("alertType"),
                "currentDisposition": data.get("currentDisposition"),
                "adverseEventFlag": data.get("adverseEventFlag", False),
                "escalationStopped": data.get("escalationStopped", False),
                "timeToHumanContactSeconds": data.get("timeToHumanContactSeconds"),
                "createdAt": created_at.isoformat() if created_at else None,
                "lastRespondedBy": data.get("lastRespondedBy"),
                # SMS-unreachable: responders must reach this participant by phone.
                "participantSmsOptedOut": data.get("participantSmsOptedOut", False),
            })

        return {"events": events}
    except Exception as e:
        logger.error(f"Failed to get active safety events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/inbound-sms")
@limiter.limit("30/minute")
def get_inbound_sms(request: Request, review_only: bool = False, limit: int = 100,
                    user: dict = Depends(verify_firebase_token)):
    """Inbound SMS log — every text a participant/responder/unknown number sends
    to the study line. review_only=true returns just the messages flagged for
    human attention (participant free-form replies, opt-outs, unmatched senders,
    unrecognized on-call commands) so a participant reaching out by text is never
    silently dropped."""
    try:
        limit = max(1, min(int(limit), 500))
        # Order by receivedAt only (single-field, auto-indexed) and filter
        # needsReview in code — avoids a composite-index dependency. Over-fetch
        # when filtering so review items aren't crowded out by recent handled ones.
        fetch = min(limit * 5, 500) if review_only else limit
        query = db.collection(INBOUND_SMS_COLLECTION).order_by(
            "receivedAt", direction=firestore.Query.DESCENDING).limit(fetch)

        messages = []
        for doc in query.stream():
            d = doc.to_dict()
            if review_only and not d.get("needsReview"):
                continue
            received = d.get("receivedAt")
            if received and hasattr(received, "timestamp"):
                received = datetime.fromtimestamp(received.timestamp())
            messages.append({
                "id": doc.id,
                "fromNumber": d.get("fromNumber"),
                "body": d.get("body"),
                "senderType": d.get("senderType"),
                "classification": d.get("classification"),
                "participantId": d.get("participantId"),
                "responderName": d.get("responderName"),
                "needsReview": d.get("needsReview", False),
                "receivedAt": received.isoformat() if received else None,
            })
            if len(messages) >= limit:
                break
        return {"messages": messages}
    except Exception as e:
        logger.error(f"Failed to get inbound SMS: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DSMB / IRB Reporting Export
# ============================================================================

@app.get("/api/admin/safety-report")
@limiter.limit("10/minute")
def generate_safety_report(
    request: Request,
    start_date: str = Query(None),
    end_date: str = Query(None),
    user: dict = Depends(verify_admin_token),
):
    """
    Generate a safety report for DSMB/IRB review (admin only).
    Includes all safety events, audit trails, response times, and dispositions.
    """
    try:
        query = db.collection(SAFETY_EVENTS_COLLECTION).order_by(
            "createdAt", direction=firestore.Query.DESCENDING
        )

        events = []
        for doc in query.stream():
            data = doc.to_dict()
            created_at = data.get("createdAt")
            if created_at and hasattr(created_at, "timestamp"):
                created_at = datetime.fromtimestamp(created_at.timestamp())

            # Apply date filters
            if start_date and created_at:
                if created_at.strftime("%Y-%m-%d") < start_date:
                    continue
            if end_date and created_at:
                if created_at.strftime("%Y-%m-%d") > end_date:
                    continue

            # Get audit trail
            trail = []
            for trail_doc in doc.reference.collection("audit_trail").order_by("loggedAt").stream():
                entry = trail_doc.to_dict()
                if entry.get("loggedAt") and hasattr(entry["loggedAt"], "timestamp"):
                    entry["loggedAt"] = datetime.fromtimestamp(entry["loggedAt"].timestamp()).isoformat()
                trail.append(entry)

            # Get follow-ups
            followups = []
            for fu_doc in db.collection(FOLLOWUP_COLLECTION).where(
                "safetyEventId", "==", doc.id
            ).order_by("scheduledAt").stream():
                fu = fu_doc.to_dict()
                if fu.get("scheduledAt") and hasattr(fu["scheduledAt"], "timestamp"):
                    fu["scheduledAt"] = datetime.fromtimestamp(fu["scheduledAt"].timestamp()).isoformat()
                if fu.get("completedAt") and hasattr(fu["completedAt"], "timestamp"):
                    fu["completedAt"] = datetime.fromtimestamp(fu["completedAt"].timestamp()).isoformat()
                followups.append(fu)

            events.append({
                "eventId": doc.id,
                "participantId": data.get("participantId"),
                "alertType": data.get("alertType"),
                "createdAt": created_at.isoformat() if created_at else None,
                "currentDisposition": data.get("currentDisposition"),
                "adverseEventFlag": data.get("adverseEventFlag", False),
                "timeToHumanContactSeconds": data.get("timeToHumanContactSeconds"),
                "firstResponseAt": data.get("firstResponseAt").isoformat() if data.get("firstResponseAt") and hasattr(data.get("firstResponseAt"), "isoformat") else None,
                "auditTrail": trail,
                "followUps": followups,
            })

        # Summary statistics
        total_events = len(events)
        adverse_events = sum(1 for e in events if e.get("adverseEventFlag"))
        avg_response_time = 0
        response_times = [e["timeToHumanContactSeconds"] for e in events if e.get("timeToHumanContactSeconds")]
        if response_times:
            avg_response_time = sum(response_times) / len(response_times)

        return {
            "reportGeneratedAt": datetime.utcnow().isoformat() + "Z",
            "reportGeneratedBy": user.get("email"),
            "dateRange": {"start": start_date, "end": end_date},
            "summary": {
                "totalSafetyEvents": total_events,
                "adverseEvents": adverse_events,
                "averageResponseTimeSeconds": round(avg_response_time, 1),
                "eventsWithDisposition": sum(1 for e in events if e.get("currentDisposition")),
                "eventsWithoutDisposition": sum(1 for e in events if not e.get("currentDisposition")),
            },
            "events": events,
        }
    except Exception as e:
        logger.error(f"Failed to generate safety report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Automated Follow-Up Schedule (24h / 48h / 72h / 7d)
# ============================================================================

FOLLOWUP_INTERVALS_HOURS = [24, 48, 72, 168]  # 24h, 48h, 72h, 7 days


@app.post("/api/safety-events/{event_id}/create-followups")
@limiter.limit("20/minute")
def create_followup_schedule(
    request: Request,
    event_id: str,
    user: dict = Depends(verify_firebase_token),
):
    """
    Create automated follow-up schedule for a safety event.
    Generates follow-ups at 24h, 48h, 72h, and 7 days after the event.
    """
    try:
        event_ref = db.collection(SAFETY_EVENTS_COLLECTION).document(event_id)
        event_doc = event_ref.get()

        if not event_doc.exists:
            raise HTTPException(status_code=404, detail="Safety event not found")

        event_data = event_doc.to_dict()
        created_at = event_data.get("createdAt")
        if created_at and hasattr(created_at, "timestamp"):
            created_at = datetime.fromtimestamp(created_at.timestamp())
        else:
            created_at = datetime.utcnow()

        # Check if follow-ups already exist
        existing = list(db.collection(FOLLOWUP_COLLECTION).where(
            "safetyEventId", "==", event_id
        ).limit(1).stream())
        if existing:
            return {"message": "Follow-ups already created for this event", "status": "already_exists"}

        followups_created = []
        for hours in FOLLOWUP_INTERVALS_HOURS:
            followup_id = str(uuid.uuid4())
            scheduled_at = created_at + timedelta(hours=hours)

            label = f"{hours}h" if hours < 168 else "7d"

            db.collection(FOLLOWUP_COLLECTION).document(followup_id).set({
                "safetyEventId": event_id,
                "participantId": event_data.get("participantId"),
                "scheduledAt": scheduled_at,
                "intervalHours": hours,
                "label": label,
                "status": "pending",
                "createdBy": user.get("email"),
                "createdAt": datetime.utcnow(),
                "completedAt": None,
                "completedBy": None,
                "notes": None,
                "outreachMethod": None,
            })

            followups_created.append({
                "id": followup_id,
                "scheduledAt": scheduled_at.isoformat() + "Z",
                "label": label,
            })

        # Log to audit trail
        event_ref.collection("audit_trail").document(str(uuid.uuid4())).set({
            "type": "followup_schedule_created",
            "followupCount": len(followups_created),
            "loggedBy": user.get("email"),
            "loggedAt": datetime.utcnow(),
        })

        logger.info(f"Created {len(followups_created)} follow-ups for safety event {event_id}")
        return {
            "message": f"Created {len(followups_created)} follow-ups",
            "followups": followups_created,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create follow-up schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/followups/upcoming")
@limiter.limit("30/minute")
def get_upcoming_followups(request: Request, user: dict = Depends(verify_firebase_token)):
    """Get all upcoming (pending) follow-ups for the dashboard."""
    try:
        followups = []
        query = db.collection(FOLLOWUP_COLLECTION).where(
            "status", "==", "pending"
        ).order_by("scheduledAt").limit(100)

        for doc in query.stream():
            data = doc.to_dict()
            scheduled_at = data.get("scheduledAt")
            if scheduled_at and hasattr(scheduled_at, "timestamp"):
                scheduled_at = datetime.fromtimestamp(scheduled_at.timestamp())

            is_overdue = scheduled_at and scheduled_at < datetime.utcnow() if scheduled_at else False

            followups.append({
                "id": doc.id,
                "safetyEventId": data.get("safetyEventId"),
                "participantId": data.get("participantId"),
                "scheduledAt": scheduled_at.isoformat() + "Z" if scheduled_at else None,
                "label": data.get("label"),
                "status": data.get("status"),
                "isOverdue": is_overdue,
            })

        return {"followups": followups}
    except Exception as e:
        logger.error(f"Failed to get upcoming follow-ups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/followups/{followup_id}/complete")
@limiter.limit("30/minute")
def complete_followup(
    request: Request,
    followup_id: str,
    body: FollowUpLog,
    user: dict = Depends(verify_firebase_token),
):
    """Mark a follow-up as completed with notes."""
    try:
        fu_ref = db.collection(FOLLOWUP_COLLECTION).document(followup_id)
        fu_doc = fu_ref.get()

        if not fu_doc.exists:
            raise HTTPException(status_code=404, detail="Follow-up not found")

        fu_data = fu_doc.to_dict()

        fu_ref.update({
            "status": body.status,
            "completedAt": datetime.utcnow(),
            "completedBy": user.get("email"),
            "notes": body.notes,
            "outreachMethod": body.outreach_method,
        })

        # Log to safety event audit trail
        safety_event_id = fu_data.get("safetyEventId")
        if safety_event_id:
            db.collection(SAFETY_EVENTS_COLLECTION).document(safety_event_id).collection(
                "audit_trail"
            ).document(str(uuid.uuid4())).set({
                "type": "followup_completed",
                "followupId": followup_id,
                "followupLabel": fu_data.get("label"),
                "status": body.status,
                "notes": body.notes,
                "loggedBy": user.get("email"),
                "loggedAt": datetime.utcnow(),
            })

        logger.info(f"Follow-up {followup_id} completed: {body.status} by {user.get('email')}")
        return {"message": "Follow-up completed", "status": body.status}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to complete follow-up: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 988 Conference / Warm Transfer Configuration
# ============================================================================

CONFERENCE_CONFIG_COLLECTION = config.col("conference_config")

# Default conference config — stored in Firestore for dashboard editability
DEFAULT_CONFERENCE_CONFIG = {
    "enabled": True,
    # TEMPORARY: Using (603) 646-7037 for testing. Replace with 988's dedicated partner line.
    "bridge_number": "+16036467037",
    "send_digits": "",  # DTMF sequence for 988's menu (e.g., "ww{phone}ww{area_code}")
    "hold_message": (
        "We hear you and we want to help. "
        "We are connecting you to the 988 Suicide and Crisis Lifeline now. "
        "Please stay on the line. This will just take a moment."
    ),
    "fallback_message": (
        "If you were disconnected, please call 988 directly. Goodbye."
    ),
}


def get_conference_config() -> dict:
    """Get conference config from Firestore, falling back to defaults."""
    try:
        doc = db.collection(CONFERENCE_CONFIG_COLLECTION).document("settings").get()
        if doc.exists:
            stored = doc.to_dict()
            # Merge with defaults so new fields are always present
            return {**DEFAULT_CONFERENCE_CONFIG, **stored}
        return DEFAULT_CONFERENCE_CONFIG.copy()
    except Exception as e:
        logger.error(f"Failed to get conference config: {e}")
        return DEFAULT_CONFERENCE_CONFIG.copy()


@app.get("/api/admin/conference-config")
@limiter.limit("30/minute")
def get_conference_config_endpoint(request: Request, user: dict = Depends(verify_firebase_token)):
    """Get the current 988 conference/warm transfer configuration."""
    conf = get_conference_config()
    return {"config": conf}


class ConferenceConfigUpdate(BaseModel):
    bridge_number: Optional[str] = None
    send_digits: Optional[str] = None
    hold_message: Optional[str] = None
    fallback_message: Optional[str] = None
    enabled: Optional[bool] = None


@app.post("/api/admin/conference-config")
@limiter.limit("10/minute")
def update_conference_config(
    request: Request,
    body: ConferenceConfigUpdate,
    user: dict = Depends(verify_firebase_token),
):
    """Update the 988 conference/warm transfer configuration."""
    try:
        update_data = {k: v for k, v in body.dict().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        update_data["updatedAt"] = datetime.utcnow()
        update_data["updatedBy"] = user.get("email")

        db.collection(CONFERENCE_CONFIG_COLLECTION).document("settings").set(
            update_data, merge=True
        )

        logger.info(f"Conference config updated by {user.get('email')}: {list(update_data.keys())}")
        return {"message": "Conference config updated", "config": get_conference_config()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update conference config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Twilio Call Response Webhook (IVR handler)
# ============================================================================

from fastapi import Form as FastAPIForm
from twilio.request_validator import RequestValidator

# Twilio webhook signature validation. These endpoints bypass the Dartmouth IP
# whitelist, so without this anyone who knows the URL could spoof a webhook
# (e.g., POST a fake "ERROR" SMS reply to stop a safety escalation).
# Set TWILIO_VALIDATE_WEBHOOKS=false only for local development/testing.
TWILIO_VALIDATE_WEBHOOKS = os.getenv("TWILIO_VALIDATE_WEBHOOKS", "true").lower() == "true"


async def _twilio_webhook_is_valid(request: Request) -> bool:
    """Validate the X-Twilio-Signature header on an incoming Twilio webhook."""
    if not TWILIO_VALIDATE_WEBHOOKS:
        return True
    if not config.TWILIO_AUTH_TOKEN:
        logger.error("[Twilio] TWILIO_AUTH_TOKEN not configured — rejecting webhook")
        return False

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        logger.warning(f"[Twilio] Missing X-Twilio-Signature on {request.url.path}")
        return False

    # Reconstruct the public URL Twilio signed — Cloud Run terminates TLS at the
    # proxy, so the ASGI scheme may be http while Twilio signed the https URL.
    url = str(request.url)
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    if forwarded_proto == "https" and url.startswith("http://"):
        url = "https://" + url[len("http://"):]

    params = {}
    if request.method == "POST":
        form = await request.form()  # Starlette caches this — handlers can re-read it
        params = dict(form)

    valid = RequestValidator(config.TWILIO_AUTH_TOKEN).validate(url, params, signature)
    if not valid:
        logger.warning(f"[Twilio] Invalid webhook signature on {request.url.path} (url={url})")
    return valid


def _twilio_forbidden() -> Response:
    return Response(content="<Response/>", media_type="application/xml", status_code=403)


@app.post("/api/twilio/call-response")
async def twilio_call_response(
    request: Request,
    participantId: str = Query(None),
    alertId: str = Query(None),
):
    """
    Twilio webhook for handling IVR responses during safety calls.
    Press 1 = Transfer to 988 (warm handoff via conference)
    Press 2 = Error / not currently in crisis (stops escalation)
    Press 3 = Was in crisis, already received support (stops escalation)
    No answer = unable to reach → on-call paged with full history
    """
    if not await _twilio_webhook_is_valid(request):
        return _twilio_forbidden()

    try:
        # Parse Twilio's POST form data
        form_data = await request.form()
        digits = form_data.get("Digits", "")
        call_sid = form_data.get("CallSid", "")

        logger.info(f"[Twilio IVR] Participant {participantId} pressed: {digits}, CallSid: {call_sid}")

        backend_url = os.getenv("BACKEND_URL", "https://socialscope-dashboard-api-436153481478.us-central1.run.app")

        import threading

        def _get_event_ref():
            """Resolve the safety event this call is about. The safety_events doc
            id IS the alertId (createSafetyEvent uses .doc(alertId)), and the IVR
            action URL carries alertId — so target it directly. This avoids
            mutating the wrong event when a participant has >1 event within a day
            (e.g. a walk-away event then a confirmed-danger event)."""
            try:
                if alertId:
                    ref = db.collection(SAFETY_EVENTS_COLLECTION).document(alertId)
                    if ref.get().exists:
                        return ref
                # Fallback (alertId missing/unknown): most-recent event for participant
                events = list(db.collection(SAFETY_EVENTS_COLLECTION)
                    .where("participantId", "==", participantId)
                    .order_by("createdAt", direction=firestore.Query.DESCENDING)
                    .limit(1).stream())
                return events[0].reference if events else None
            except Exception as e:
                logger.warning(f"[Twilio IVR] Failed to find safety event: {e}")
                return None

        if digits == "2":
            # Press 2: Transfer to 988 Suicide & Crisis Lifeline
            # (digit mapping aligned with SMS where 1/ERROR = error)
            # ZERO Firestore reads here — return TwiML INSTANTLY
            conference_room = f"crisis-{participantId}-{alertId or uuid.uuid4().hex[:8]}"

            if twilio_client:
                # Place participant in conference with hold audio immediately
                twiml = (
                    '<Response>'
                    '<Say voice="Polly.Joanna">Thank you. We will now try to transfer you to the '
                    '988 Suicide and Crisis Lifeline. Please stay on the line.</Say>'
                    '<Dial>'
                    f'<Conference startConferenceOnEnter="false" endConferenceOnExit="true" '
                    f'waitUrl="{backend_url}/api/twilio/hold-music" '
                    f'statusCallback="{backend_url}/api/twilio/conference-events'
                    f'?participantId={participantId}&amp;alertId={alertId}" '
                    f'statusCallbackEvent="join leave end" '
                    f'beep="false">'
                    f'{conference_room}'
                    f'</Conference>'
                    '</Dial>'
                    '<Say voice="Polly.Joanna">If you were disconnected, please call 988 directly. Goodbye.</Say>'
                    '</Response>'
                )

                # Background thread: read config + dial bridge — NO blocking the TwiML
                def _redirect_participant_to_direct_988(reason: str):
                    """Fallback: pull the participant out of the conference hold loop
                    and dial the Lifeline directly. Without this, a participant whose
                    bridge call can't be placed would sit on hold indefinitely.
                    NOTE: Twilio cannot <Dial> the 988 short code — PSTN dialing
                    requires E.164, so use the configured bridge number or the
                    Lifeline's underlying toll-free number."""
                    try:
                        fallback_number = (get_conference_config().get("bridge_number")
                                           or "+18002738255")  # 988 Lifeline E.164
                        twilio_client.calls(call_sid).update(
                            twiml=(
                                '<Response>'
                                '<Say voice="Polly.Joanna">We are connecting you directly to the '
                                '988 Suicide and Crisis Lifeline now. Please stay on the line.</Say>'
                                f'<Dial timeout="60">{fallback_number}</Dial>'
                                '<Say voice="Polly.Joanna">If you were disconnected, please call 988 directly. '
                                'If you are in immediate danger, please call 911. Goodbye.</Say>'
                                '</Response>'
                            )
                        )
                        logger.warning(f"[Conference] Direct 988 fallback for {participantId}: {reason}")
                        event_ref = _get_event_ref()
                        if event_ref:
                            event_ref.collection("audit_trail").document().set({
                                "type": "direct_988_fallback",
                                "reason": reason,
                                "callSid": call_sid,
                                "loggedBy": "system",
                                "loggedAt": datetime.utcnow(),
                            })
                    except Exception as redirect_err:
                        logger.error(f"[Conference] Failed to redirect participant to direct 988: {redirect_err}", exc_info=True)

                def dial_bridge_and_update():
                    try:
                        # Read conference config IN the background thread
                        conf = get_conference_config()

                        if not conf.get("enabled") or not conf.get("bridge_number"):
                            logger.warning("[Conference] Conference not enabled or no bridge number")
                            _redirect_participant_to_direct_988("conference_disabled_or_no_bridge_number")
                            return

                        # DIAL FIRST — this is the time-critical part
                        raw_digits = conf.get("send_digits", "")
                        send_digits = ""

                        if raw_digits and ("{phone}" in raw_digits or "{area_code}" in raw_digits):
                            try:
                                participant_doc = db.collection(config.col("participants")).document(participantId).get()
                                if participant_doc.exists:
                                    p_data = participant_doc.to_dict()
                                    p_phone = (p_data.get("phone") or p_data.get("phoneNumber") or "").replace("+1", "").replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
                                    p_area = p_phone[:3] if len(p_phone) >= 3 else ""
                                    # Interleave 'w' (0.5s pause) between each digit for IVR reliability
                                    phone_spaced = "w".join(list(p_phone))
                                    area_spaced = "w".join(list(p_area))
                                    send_digits = raw_digits.replace("{phone}", phone_spaced).replace("{area_code}", area_spaced)
                            except Exception as e:
                                logger.warning(f"[Conference] Could not fetch participant phone for sendDigits: {e}")
                                send_digits = raw_digits.replace("{phone}", "").replace("{area_code}", "")
                        elif raw_digits:
                            send_digits = raw_digits

                        # Build join-conference callback URL
                        dtmf_audio_url = conf.get("dtmf_audio_url", "")
                        join_url = (
                            f"{backend_url}/api/twilio/join-conference"
                            f"?room={conference_room}"
                            f"&participantId={participantId}"
                            f"&alertId={alertId}"
                        )
                        if dtmf_audio_url:
                            from urllib.parse import quote
                            join_url += f"&dtmf_audio_url={quote(dtmf_audio_url, safe='')}"

                        call_params = {
                            "to": conf["bridge_number"],
                            "from_": config.TWILIO_FROM_NUMBER,
                            "url": join_url,
                            "timeout": 60,
                        }
                        # Use send_digits for IVR signaling (inaudible DTMF)
                        # unless dtmf_audio_url is set (audible audio tones instead)
                        if send_digits and not dtmf_audio_url:
                            call_params["send_digits"] = send_digits

                        bridge_call = twilio_client.calls.create(**call_params)

                        logger.info(
                            f"[Conference] Bridge call initiated: {bridge_call.sid} "
                            f"to {conf['bridge_number']} for room {conference_room}"
                        )

                        # NOW do Firestore updates (after call is placed).
                        # IMPORTANT: do NOT mark the event resolved here — the
                        # bridge call has only been *placed*, not yet connected.
                        # escalationStopped is set only when the 988 bridge leg
                        # actually JOINS the conference (twilio_conference_events).
                        # If it never connects, the event stays unresolved and the
                        # escalation scheduler pages the on-call researcher.
                        event_ref = _get_event_ref()
                        if event_ref:
                            event_ref.update({
                                "adverseEventFlag": True,
                                "participantConfirmedCrisis": True,
                                "participant988Requested": True,
                                "participant988RequestedAt": datetime.utcnow(),
                                "notifyEmergencyContacts": True,
                                "conferenceRoom": conference_room,
                                "bridgeCallSid": bridge_call.sid,
                                "bridgeCallInitiatedAt": datetime.utcnow(),
                            })
                            event_ref.collection("audit_trail").document().set({
                                "type": "participant_ivr_crisis_and_bridge",
                                "response": "crisis_confirmed_988",
                                "digits": digits,
                                "callSid": call_sid,
                                "bridgeCallSid": bridge_call.sid,
                                "bridgeNumber": conf["bridge_number"],
                                "conferenceRoom": conference_room,
                                "loggedBy": "system",
                                "loggedAt": datetime.utcnow(),
                            })

                    except Exception as e:
                        logger.error(f"[Conference] Failed to dial bridge: {e}", exc_info=True)
                        # Don't leave the participant on infinite hold — dial 988 directly
                        _redirect_participant_to_direct_988(f"bridge_dial_failed: {e}")
                        try:
                            event_ref = _get_event_ref()
                            if event_ref:
                                event_ref.collection("audit_trail").document().set({
                                    "type": "bridge_call_failed",
                                    "error": str(e),
                                    "conferenceRoom": conference_room,
                                    "loggedBy": "system",
                                    "loggedAt": datetime.utcnow(),
                                })
                        except Exception:
                            pass

                threading.Thread(target=dial_bridge_and_update, daemon=True).start()

            else:
                # Fallback: no Twilio client available — direct cold transfer
                logger.warning("[Twilio IVR] No Twilio client, falling back to direct <Dial>988</Dial>")
                twiml = (
                    '<Response>'
                    '<Say voice="Polly.Joanna">Thank you. We will now try to transfer you to the '
                    '988 Suicide and Crisis Lifeline. Please stay on the line. '
                    'If the call does not connect, you can call or text 988 directly at any time. '
                    'If you are in immediate danger, please call 911 now.</Say>'
                    f'<Dial timeout="60">{get_conference_config().get("bridge_number") or "+18002738255"}</Dial>' 
                    '<Say voice="Polly.Joanna">If you were disconnected, please call 988 directly. Goodbye.</Say>'
                    '</Response>'
                )

        elif digits == "1":
            # Press 1: Error — not currently in a crisis state (same meaning as
            # texting 1/ERROR — digits mean the same thing on every channel)
            twiml = (
                '<Response>'
                '<Say voice="Polly.Joanna">'
                'Thank you for letting us know. We have recorded that your response was an error '
                'and that you are not currently in a crisis state. You may now hang up.'
                '</Say>'
                '</Response>'
            )

            def update_event_press1_error():
                event_ref = _get_event_ref()
                if event_ref:
                    event_ref.update({
                        "currentDisposition": "false_alarm",
                        "escalationStopped": True,
                        "participantResolved": True,
                        "participantResolvedAt": datetime.utcnow(),
                        "participantResolvedVia": "ivr_press1_error",
                        "lastRespondedAt": datetime.utcnow(),
                    })
                    event_ref.collection("audit_trail").document().set({
                        "type": "participant_ivr_response",
                        "response": "error_not_in_crisis",
                        "digits": "1",
                        "callSid": call_sid,
                        "loggedBy": "system",
                        "loggedAt": datetime.utcnow(),
                    })
            threading.Thread(target=update_event_press1_error, daemon=True).start()

        elif digits == "3":
            # Press 3: Was in crisis but already received support
            twiml = (
                '<Response>'
                '<Say voice="Polly.Joanna">'
                'Thank you for letting us know. We have recorded that you were previously in a crisis state, '
                'but that you are no longer in a crisis state because you have already received support. '
                'If you need additional immediate support later, you can call or text 988 at any time. '
                'You may now hang up.'
                '</Say>'
                '</Response>'
            )

            def update_event_press3():
                event_ref = _get_event_ref()
                if event_ref:
                    event_ref.update({
                        "currentDisposition": "crisis_resolved_with_support",
                        "escalationStopped": True,
                        "participantResolved": True,
                        "participantResolvedAt": datetime.utcnow(),
                        "participantResolvedVia": "ivr_press3_resolved",
                        "lastRespondedAt": datetime.utcnow(),
                    })
                    event_ref.collection("audit_trail").document().set({
                        "type": "participant_ivr_response",
                        "response": "crisis_resolved_with_support",
                        "digits": "3",
                        "callSid": call_sid,
                        "loggedBy": "system",
                        "loggedAt": datetime.utcnow(),
                    })
            threading.Thread(target=update_event_press3, daemon=True).start()

        else:
            # Unrecognized input — replay options once more
            twiml = (
                '<Response>'
                f'<Gather numDigits="1" action="{backend_url}'
                f'/api/twilio/call-response?participantId={participantId}&alertId={alertId}" method="POST" timeout="20">'
                '<Say voice="Polly.Joanna">'
                'Sorry, we did not understand your response. '
                'Press 1 if your response was an error and you are not currently in a crisis state. '
                'Press 2 to be transferred to the 988 Suicide and Crisis Lifeline. '
                'Press 3 if you were in a crisis state but have already received support.'
                '</Say>'
                '</Gather>'
                '<Say voice="Polly.Joanna">'
                'We did not receive a valid response. Because your earlier response indicated that you may '
                'need immediate support, we encourage you to call or text 988 now, or call 911 if you are '
                'in immediate danger. Goodbye.'
                '</Say>'
                '</Response>'
            )

            # No response — mark as unable to reach in background
            if not digits:
                def update_no_response():
                    event_ref = _get_event_ref()
                    if event_ref:
                        event_ref.update({"participantCallNoResponse": True})
                        event_ref.collection("audit_trail").document().set({
                            "type": "participant_ivr_no_response",
                            "callSid": call_sid,
                            "loggedBy": "system",
                            "loggedAt": datetime.utcnow(),
                        })
                threading.Thread(target=update_no_response, daemon=True).start()

        return Response(content=twiml, media_type="application/xml")

    except Exception as e:
        logger.error(f"[Twilio IVR] Error: {e}", exc_info=True)
        return Response(
            content='<Response><Say>An error occurred. Please call 988 if you need help.</Say></Response>',
            media_type="application/xml",
        )


# ============================================================================
# Twilio Conference Warm Transfer Webhooks
# ============================================================================


@app.post("/api/twilio/hold-music")
async def twilio_hold_music(request: Request):
    """
    TwiML endpoint for conference hold audio.
    Plays reassuring messages on loop while the 988 bridge call connects.
    Called via the Conference waitUrl attribute. Loops indefinitely via <Redirect/>.
    """
    if not await _twilio_webhook_is_valid(request):
        return _twilio_forbidden()

    # Rotate through reassuring messages so it doesn't feel like a broken recording
    twiml = (
        '<Response>'
        '<Say voice="Polly.Joanna">'
        'Thank you for staying on the line. We are working to connect you to the '
        '988 Suicide and Crisis Lifeline now. Please stay on the line.'
        '</Say>'
        '<Pause length="5"/>'
        '<Say voice="Polly.Joanna">'
        'Your call is important. A trained crisis counselor will be with you shortly. '
        'If you are experiencing a long wait, you can also call or text 988 directly at any time.'
        '</Say>'
        '<Pause length="5"/>'
        '<Say voice="Polly.Joanna">'
        'We are still connecting your call. Please continue to hold. '
        'If you are in an urgent crisis and need immediate help, please hang up and call 911 now.'
        '</Say>'
        '<Pause length="5"/>'
        '<Say voice="Polly.Joanna">Please continue to hold. We are connecting you now.</Say>'
        '<Pause length="5"/>'
        '<Redirect/>'
        '</Response>'
    )
    return Response(content=twiml, media_type="application/xml")


@app.post("/api/twilio/join-conference")
async def twilio_join_conference(
    request: Request,
    room: str = Query(None),
    participantId: str = Query(None),
    alertId: str = Query(None),
    dtmf_audio_url: str = Query(None),
):
    """
    TwiML callback for the bridge call (988's dedicated line).
    Fires AFTER the bridge call is answered and sendDigits completes.
    Returns Conference TwiML to join the participant's conference room.

    If dtmf_audio_url is provided, plays audible DTMF audio tones first
    (used when 988's IVR needs to hear dial tones for routing).

    startConferenceOnEnter=true causes the participant's hold audio to stop
    and connects them to the bridge caller (988 counselor) seamlessly.
    """
    if not await _twilio_webhook_is_valid(request):
        return _twilio_forbidden()

    logger.info(f"[Conference] Bridge answered, joining room: {room} (participant: {participantId})")

    # Log to audit trail
    try:
        events = list(db.collection(SAFETY_EVENTS_COLLECTION)
            .where("participantId", "==", participantId)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(1).stream())
        if events:
            events[0].reference.collection("audit_trail").document().set({
                "type": "bridge_joined_conference",
                "conferenceRoom": room,
                "loggedBy": "system",
                "loggedAt": datetime.utcnow(),
            })
    except Exception as e:
        logger.error(f"[Conference] Failed to log bridge join: {e}")

    backend_url = os.getenv("BACKEND_URL", "https://socialscope-dashboard-api-436153481478.us-central1.run.app")

    # Build TwiML — optionally play DTMF audio before joining conference
    # The audio file has a built-in initial pause, so no extra <Pause> needed
    dtmf_section = ""
    if dtmf_audio_url:
        dtmf_section = (
            f'<Play>{dtmf_audio_url}</Play>'
            '<Say voice="Polly.Joanna">The participant from the SocialScope study at Dartmouth has been connected. '
            'They are now on the line and you can initiate the call.</Say>'
        )

    twiml = (
        '<Response>'
        f'{dtmf_section}'
        '<Dial>'
        f'<Conference startConferenceOnEnter="true" endConferenceOnExit="true" '
        f'beep="false" '
        f'statusCallback="{backend_url}/api/twilio/conference-events'
        f'?participantId={participantId}&amp;alertId={alertId}&amp;leg=bridge" '
        f'statusCallbackEvent="join leave end">'
        f'{room}'
        f'</Conference>'
        '</Dial>'
        '</Response>'
    )
    return Response(content=twiml, media_type="application/xml")


@app.post("/api/twilio/conference-events")
async def twilio_conference_events(
    request: Request,
    participantId: str = Query(None),
    alertId: str = Query(None),
    leg: str = Query(None),
):
    """
    Status callback for conference events (join, leave, end).
    Logs events to the safety event audit trail for DSMB reporting.
    """
    if not await _twilio_webhook_is_valid(request):
        return _twilio_forbidden()

    try:
        form_data = await request.form()
        event = form_data.get("StatusCallbackEvent", "")
        conference_sid = form_data.get("ConferenceSid", "")
        call_sid = form_data.get("CallSid", "")
        friendly_name = form_data.get("FriendlyName", "")

        logger.info(
            f"[Conference Event] {event} | room={friendly_name} | "
            f"participant={participantId} | leg={leg} | callSid={call_sid}"
        )

        # Resolve the event by alertId (== safety_events doc id) so a 988-join is
        # recorded against the event the call was actually about, not whatever is
        # most recent. Fall back to most-recent only if alertId is missing.
        if participantId:
            event_ref = None
            if alertId:
                candidate = db.collection(SAFETY_EVENTS_COLLECTION).document(alertId)
                if candidate.get().exists:
                    event_ref = candidate
            if event_ref is None:
                events = list(db.collection(SAFETY_EVENTS_COLLECTION)
                    .where("participantId", "==", participantId)
                    .order_by("createdAt", direction=firestore.Query.DESCENDING)
                    .limit(1).stream())
                event_ref = events[0].reference if events else None

            if event_ref is not None:
                event_snap = event_ref.get()
                audit_data = {
                    "type": f"conference_{event}",
                    "conferenceSid": conference_sid,
                    "conferenceRoom": friendly_name,
                    "callSid": call_sid,
                    "leg": leg or "participant",
                    "loggedBy": "system",
                    "loggedAt": datetime.utcnow(),
                }

                # When the 988 bridge leg JOINS, the participant is actually
                # connected to the Lifeline — this is the "988 connection happened"
                # signal. Mark the event resolved so the escalation scheduler does
                # NOT page the on-call researcher (988 is what we'd do anyway).
                if event == "join" and leg == "bridge":
                    event_ref.update({
                        "conf988Connected": True,
                        "conf988ConnectedAt": datetime.utcnow(),
                        "currentDisposition": "escalated_988",
                        "escalationStopped": True,
                        # participantResolved kept consistent with the other
                        # resolve paths (press-1, press-3, SMS ERROR, app push)
                        "participantResolved": True,
                        "participantResolvedAt": datetime.utcnow(),
                        "participantResolvedVia": "988_connected",
                        "lastRespondedAt": datetime.utcnow(),
                    })
                    audit_data["resolution"] = "988_connected"

                # On conference end, record duration if possible
                if event == "end":
                    event_data = event_snap.to_dict() if event_snap and event_snap.exists else {}
                    bridge_initiated = event_data.get("bridgeCallInitiatedAt")
                    if bridge_initiated:
                        if hasattr(bridge_initiated, "timestamp"):
                            # utcfromtimestamp keeps the subtraction in UTC; plain
                            # fromtimestamp would shift to server-local and skew duration.
                            duration = (datetime.utcnow() - datetime.utcfromtimestamp(bridge_initiated.timestamp())).total_seconds()
                        else:
                            duration = (datetime.utcnow() - bridge_initiated).total_seconds()
                        audit_data["conferenceDurationSeconds"] = duration
                        event_ref.update({"conferenceDurationSeconds": duration})

                event_ref.collection("audit_trail").document().set(audit_data)

    except Exception as e:
        logger.error(f"[Conference Event] Error processing: {e}", exc_info=True)

    # Twilio expects 200 OK for status callbacks
    return Response(content="<Response/>", media_type="application/xml")


# ============================================================================
# Twilio SMS Reply Webhook — Handles replies from on-call staff AND participants
# ============================================================================

# SMS command mapping (on-call staff)
# SMS_DISPOSITION_MAP and PARTICIPANT_ERROR_KEYWORDS now live in sms_utils.py
# (single source, unit-tested) and are imported at the top of this file.

INBOUND_SMS_COLLECTION = config.col("inbound_sms")


def _log_inbound_sms(from_number, body, sender_type, classification,
                     participant_id=None, responder_name=None, needs_review=False):
    """Persist EVERY inbound SMS so nothing a participant or responder texts is
    invisible to the study team. Best-effort: a logging failure must never block
    the webhook's reply. needs_review flags messages a human should look at
    (e.g. a participant texting free-form during/after an alert)."""
    try:
        doc = {
            "fromNumber": from_number,
            "fromNormalized": normalize_phone(from_number),
            "body": body,
            "senderType": sender_type,            # participant | oncall | unknown
            "classification": classification,
            "participantId": participant_id,
            "responderName": responder_name,
            "needsReview": needs_review,
            "handled": not needs_review,
            "receivedAt": datetime.utcnow(),
        }
        db.collection(INBOUND_SMS_COLLECTION).document(str(uuid.uuid4())).set(doc)
    except Exception as e:
        logger.error(f"[SMS Reply] Failed to log inbound SMS from {from_number}: {e}")


def _find_participant_by_phone(phone_number: str):
    """
    Look up a participant by phone number. Returns (participant_id, doc_data) or (None, None).
    Checks both 'phone' and 'phoneNumber' fields, with and without +1 prefix.
    """
    # Canonical digits-only form (see phone_utils — single source of truth)
    normalized = normalize_phone(phone_number)

    # Query participants collection for matching phone
    participants_ref = db.collection(config.col("participants"))

    # Fast path: indexed equality on common stored formats (incl. normalized field)
    for phone_field in ["phoneNormalized", "phone", "phoneNumber"]:
        for fmt in [normalized, f"+1{normalized}", f"1{normalized}"]:
            try:
                docs = list(participants_ref.where(phone_field, "==", fmt).limit(1).stream())
                if docs:
                    return docs[0].id, docs[0].to_dict()
            except Exception:
                pass

    # Fallback: stored phones may carry formatting ("(603) 555-1234") that
    # equality can never match — scan and compare digits-only. Participant
    # counts are small (hundreds), and this runs in a webhook worker thread.
    try:
        for doc in participants_ref.stream():
            data = doc.to_dict()
            if any(phones_match(data.get(field), normalized) for field in ("phone", "phoneNumber")):
                return doc.id, data
    except Exception as e:
        logger.warning(f"[SMS Reply] Fallback phone scan failed: {e}")

    return None, None


@app.post("/api/twilio/sms-reply")
async def twilio_sms_reply(request: Request):
    """
    Twilio webhook for incoming SMS replies.

    1. If sender is a PARTICIPANT:
       - ERROR/1/ONE/MISTAKE → stops escalation (false alarm)
       - Anything else → responds with structured fields notice + crisis resources
    2. If sender is ON-CALL STAFF:
       - ACK, SAFE, SUPPORT, NOREACH, FALSE, 988, ER, ONGOING → disposition commands
    3. Unknown sender → generic response
    """
    if not await _twilio_webhook_is_valid(request):
        return _twilio_forbidden()

    try:
        form_data = await request.form()
        body = form_data.get("Body", "").strip()
        from_number = form_data.get("From", "").replace("+1", "").replace("+", "")

        logger.info(f"[SMS Reply] From: {from_number}, Body: '{body}'")

        # ─── STEP 1: Check if sender is a participant ───
        from fastapi.concurrency import run_in_threadpool
        participant_id, participant_data = await run_in_threadpool(_find_participant_by_phone, from_number)

        if participant_id:
            logger.info(f"[SMS Reply] Identified as participant: {participant_id}")

            # Opt-out: the carrier will now block ALL future SMS to this number,
            # including crisis-escalation texts. Flag the participant as
            # SMS-unreachable and log for review — this is safety-relevant.
            if is_optout(body):
                try:
                    db.collection(config.col("participants")).document(participant_id).set(
                        {"smsOptedOut": True, "smsOptedOutAt": datetime.utcnow()}, merge=True)
                except Exception as e:
                    logger.error(f"[SMS Reply] Failed to flag opt-out for {participant_id}: {e}")
                _log_inbound_sms(from_number, body, "participant", "optout",
                                 participant_id=participant_id, needs_review=True)
                # Twilio auto-sends the compliance opt-out confirmation.
                return Response(content='<Response></Response>', media_type="application/xml")

            if is_resubscribe(body):
                try:
                    db.collection(config.col("participants")).document(participant_id).set(
                        {"smsOptedOut": False, "smsResubscribedAt": datetime.utcnow()}, merge=True)
                except Exception as e:
                    logger.error(f"[SMS Reply] Failed to clear opt-out for {participant_id}: {e}")
                _log_inbound_sms(from_number, body, "participant", "resubscribe",
                                 participant_id=participant_id)

            # Check if this is an ERROR/false-alarm reply
            if is_participant_error_reply(body):
                # Stop escalation — participant says it was an error
                import threading

                def _stop_escalation():
                    try:
                        # NOTE: only (participantId, createdAt) has a composite index —
                        # adding escalationStopped to the query throws FAILED_PRECONDITION.
                        # Fetch latest events and filter in code instead.
                        events = [
                            e for e in db.collection(SAFETY_EVENTS_COLLECTION)
                            .where("participantId", "==", participant_id)
                            .order_by("createdAt", direction=firestore.Query.DESCENDING)
                            .limit(5).stream()
                            if not e.to_dict().get("escalationStopped")
                        ][:1]

                        if events:
                            event_ref = events[0].reference
                            event_ref.update({
                                "currentDisposition": "false_alarm",
                                "escalationStopped": True,
                                "participantResolved": True,
                                "participantResolvedAt": datetime.utcnow(),
                                "participantResolvedVia": "sms",
                                "lastRespondedAt": datetime.utcnow(),
                            })
                            event_ref.collection("audit_trail").document().set({
                                "type": "participant_sms_error_reply",
                                "response": body,
                                "participantId": participant_id,
                                "fromNumber": from_number,
                                "loggedBy": "system",
                                "loggedAt": datetime.utcnow(),
                            })
                            logger.info(f"[SMS Reply] Participant {participant_id} replied ERROR — escalation stopped")
                    except Exception as e:
                        logger.error(f"[SMS Reply] Failed to stop escalation for {participant_id}: {e}")

                threading.Thread(target=_stop_escalation, daemon=True).start()

                _log_inbound_sms(from_number, body, "participant", "participant_error_stop",
                                 participant_id=participant_id)
                return Response(
                    content='<Response><Message>Thank you. We have noted that this was an error. '
                            'If you ever need support, please call 988 (Suicide &amp; Crisis Lifeline). '
                            'Take care.</Message></Response>',
                    media_type="application/xml",
                )
            else:
                # Non-error free-form reply from a participant. We can't action
                # it automatically, but for a suicide-prevention study it must NOT
                # be invisible — log it flagged for human review so the team sees
                # a participant reached out (even if the content is concerning).
                _log_inbound_sms(from_number, body, "participant", "participant_freeform",
                                 participant_id=participant_id, needs_review=True)
                return Response(
                    content='<Response><Message>This is an automated research system (SocialScope, Dartmouth College). '
                            'We are unable to monitor or respond to text messages from this number. '
                            'Responses must be structured (reply ERROR or 1 if your earlier response was accidental).\n\n'
                            'If you are in crisis:\n'
                            '- Call 911 or go to your nearest emergency room\n'
                            '- Call 988 (Suicide &amp; Crisis Lifeline)\n'
                            '- Text HOME to 741741 (Crisis Text Line)</Message></Response>',
                    media_type="application/xml",
                )

        # ─── STEP 2: Check if sender is on-call staff ───
        # Match on normalized phone, not raw string equality: the roster stores
        # whatever format the admin typed ("(603) 555-1234", "+16035551234"),
        # while from_number is only +/+1-stripped. Without normalization an
        # on-call responder's ACK/SAFE/988 reply is treated as an unknown sender
        # and the disposition is silently dropped — a safety failure.
        responder_name = None
        for doc in db.collection(ONCALL_COLLECTION).stream():
            data = doc.to_dict()
            if phones_match(data.get("phone"), from_number):
                responder_name = data.get("name", doc.id)
                break

        if not responder_name:
            # Check alert_recipients as fallback
            doc = db.collection(ALERT_RECIPIENTS_COLLECTION).document(from_number).get()
            if doc.exists:
                responder_name = doc.to_dict().get("name", from_number)

        if not responder_name:
            # Unknown sender — could be anyone, but could also be a participant
            # whose phone isn't on file. Log flagged for review so an unmatched
            # participant reaching out isn't silently dropped.
            logger.warning(f"[SMS Reply] Unknown sender: {from_number}")
            _log_inbound_sms(from_number, body, "unknown",
                             "optout" if is_optout(body) else "unknown_sender",
                             needs_review=True)
            return Response(
                content='<Response><Message>This is an automated research system (SocialScope, Dartmouth College). '
                        'This number is not monitored for incoming messages.\n\n'
                        'If you are in crisis:\n'
                        '- Call 911 or go to your nearest emergency room\n'
                        '- Call 988 (Suicide &amp; Crisis Lifeline)\n'
                        '- Text HOME to 741741 (Crisis Text Line)</Message></Response>',
                media_type="application/xml",
            )

        # Parse the command
        command = body.split()[0] if body else ""
        disposition = parse_oncall_command(body)

        if not disposition:
            _log_inbound_sms(from_number, body, "oncall", "oncall_unknown_command",
                             responder_name=responder_name, needs_review=True)
            return Response(
                content='<Response><Message>Unknown command. Reply: ACK, SAFE, SUPPORT, NOREACH, FALSE, 988, ER, or ONGOING</Message></Response>',
                media_type="application/xml",
            )

        # Find unresolved safety events (most recent first)
        events = list(db.collection(SAFETY_EVENTS_COLLECTION)
            .where("escalationStopped", "==", False)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(20).stream())

        # Also include acknowledged/ongoing events
        if not events:
            events = list(db.collection(SAFETY_EVENTS_COLLECTION)
                .where("currentDisposition", "==", "ongoing")
                .order_by("createdAt", direction=firestore.Query.DESCENDING)
                .limit(20).stream())

        if not events:
            return Response(
                content='<Response><Message>No active safety events found.</Message></Response>',
                media_type="application/xml",
            )

        # Disambiguate among concurrent crises. Escalation pages include the
        # participant ID; the responder can include it in the reply to target a
        # specific event. With multiple active events and no ID given, do NOT
        # guess — replying about participant A must never silently resolve B.
        pid_in_msg = re.search(r"\b(\d{9})\b", body)
        if pid_in_msg:
            target_pid = pid_in_msg.group(1)
            matching = [e for e in events if e.to_dict().get("participantId") == target_pid]
            if not matching:
                return Response(
                    content=f'<Response><Message>No active safety event for participant {target_pid}.</Message></Response>',
                    media_type="application/xml",
                )
            event_doc = matching[0]
        else:
            distinct_pids = {e.to_dict().get("participantId") for e in events}
            if len(distinct_pids) > 1:
                example = sorted(p for p in distinct_pids if p)[0]
                return Response(
                    content=f'<Response><Message>Multiple active safety events are open ('
                            f'{", ".join(sorted(p for p in distinct_pids if p))}). '
                            f'Reply with the participant ID and command (e.g. "{command} {example}"), '
                            f'or use the dashboard to log the disposition.</Message></Response>',
                    media_type="application/xml",
                )
            event_doc = events[0]
        event_data = event_doc.to_dict()
        participant_id = event_data.get("participantId", "unknown")

        # Apply the disposition
        update_data = {
            "lastRespondedBy": responder_name,
            "lastRespondedAt": datetime.utcnow(),
        }

        if disposition == "acknowledged":
            update_data["acknowledged"] = True
            update_data["acknowledgedAt"] = datetime.utcnow()
            update_data["acknowledgedBy"] = responder_name
            reply_msg = f"Acknowledged. Event for {participant_id} — you're on it. Reply ONGOING/SAFE/SUPPORT/988/ER when resolved."
        elif disposition == "ongoing":
            update_data["currentDisposition"] = "ongoing"
            update_data["lastCheckInAt"] = datetime.utcnow()
            reply_msg = f"Checked in — still working on {participant_id}. Next check-in in 1 hour."
        else:
            update_data["currentDisposition"] = disposition
            update_data["escalationStopped"] = True
            if not event_data.get("firstResponseAt"):
                created_at = event_data.get("createdAt")
                if created_at and hasattr(created_at, "timestamp"):
                    # utcfromtimestamp (not fromtimestamp) so this UTC subtraction
                    # isn't skewed by the server's local offset — matches log_disposition.
                    response_time = (datetime.utcnow() - datetime.utcfromtimestamp(created_at.timestamp())).total_seconds()
                    update_data["timeToHumanContactSeconds"] = response_time
                    update_data["firstResponseAt"] = datetime.utcnow()
            if disposition in ("escalated_988", "escalated_er", "contacted_needs_support"):
                update_data["adverseEventFlag"] = True

            labels = {
                "contacted_safe": "Safe",
                "contacted_needs_support": "Needs support",
                "unable_to_reach": "Unable to reach",
                "false_alarm": "False alarm",
                "escalated_988": "Escalated to 988",
                "escalated_er": "Escalated to ER",
            }
            reply_msg = f"Disposition logged for {participant_id}: {labels.get(disposition, disposition)}. Escalation stopped."

        event_doc.reference.update(update_data)

        # Log to audit trail
        event_doc.reference.collection("audit_trail").document().set({
            "type": "sms_disposition",
            "disposition": disposition,
            "command": command,
            "respondedBy": responder_name,
            "fromNumber": from_number,
            "loggedBy": "sms_webhook",
            "loggedAt": datetime.utcnow(),
        })

        logger.info(f"[SMS Reply] {responder_name} replied '{command}' -> {disposition} for {participant_id}")

        _log_inbound_sms(from_number, body, "oncall", f"oncall_disposition:{disposition}",
                         participant_id=participant_id, responder_name=responder_name)

        return Response(
            content=f'<Response><Message>{reply_msg}</Message></Response>',
            media_type="application/xml",
        )

    except Exception as e:
        logger.error(f"[SMS Reply] Error: {e}", exc_info=True)
        return Response(
            content='<Response><Message>Error processing reply. Please use the dashboard.</Message></Response>',
            media_type="application/xml",
        )


# ============================================================================
# Twilio Incoming Voice Call Handler
# Plays automated message when someone calls the Twilio number directly
# ============================================================================

@app.post("/api/twilio/incoming-call")
@app.get("/api/twilio/incoming-call")
async def twilio_incoming_call(request: Request):
    """
    Twilio webhook for incoming voice calls to the study number.
    Plays a message explaining this is an automated system and provides crisis resources.
    """
    if not await _twilio_webhook_is_valid(request):
        return _twilio_forbidden()

    logger.info("[Twilio Incoming Call] Received incoming call")

    twiml = (
        '<Response>'
        '<Say voice="Polly.Joanna">'
        'Hello. You have reached the SocialScope research study automated system at Dartmouth College. '
        'This phone number is part of an automated research system and is not monitored for incoming calls. '
        'We are unable to take your call.'
        '</Say>'
        '<Pause length="1"/>'
        '<Say voice="Polly.Joanna">'
        'If you are experiencing a mental health crisis, please hang up and call 988 for the Suicide and Crisis Lifeline, '
        'call 911, or go to your nearest emergency room. '
        'You can also text HOME to 741741 for the Crisis Text Line.'
        '</Say>'
        '<Pause length="1"/>'
        '<Say voice="Polly.Joanna">'
        'If you are a study participant and need to reach the research team, '
        'please contact us through the SocialScope app or email the study team directly. '
        'Thank you and take care. Goodbye.'
        '</Say>'
        '</Response>'
    )

    return Response(content=twiml, media_type="application/xml")


# ============================================================================
# Compliance Notifications — Email + Push
# ============================================================================

from compliance_notifications import (
    LOW_COMPLIANCE_TEMPLATES, WEEKLY_REPORT_TEMPLATES, COMPLIANCE_LEVELS,
    select_template, pipe_template, get_compliance_level,
    send_compliance_email, send_push_notification,
    calculate_participant_compliance, calculate_weekly_compliance,
)

NOTIFICATION_HISTORY_COLLECTION = config.col("notification_history")


class SendNotificationRequest(BaseModel):
    participant_id: str
    category: str  # "ema", "screenshots", "weekly"
    template_index: Optional[int] = None  # Specific template, or None for random
    delivery_methods: List[str] = ["email"]  # "email", "push", or both
    custom_subject: Optional[str] = None
    custom_body: Optional[str] = None


@app.get("/api/compliance/{participant_id}")
@limiter.limit("30/minute")
def get_participant_compliance(
    request: Request, participant_id: str,
    days: int = Query(3), user: dict = Depends(verify_firebase_token),
):
    """Get compliance stats for a participant."""
    try:
        stats = calculate_participant_compliance(participant_id, db, days=days)

        # Also get weekly for the badge
        weekly = calculate_weekly_compliance(participant_id, db)

        # Check notification history
        history = []
        try:
            hist_query = db.collection(NOTIFICATION_HISTORY_COLLECTION).where(
                "participantId", "==", participant_id
            ).order_by("sentAt", direction=firestore.Query.DESCENDING).limit(20)
            for doc in hist_query.stream():
                d = doc.to_dict()
                sent_at = d.get("sentAt")
                if sent_at and hasattr(sent_at, "timestamp"):
                    sent_at = datetime.fromtimestamp(sent_at.timestamp())
                history.append({
                    "id": doc.id,
                    "category": d.get("category"),
                    "subject": d.get("subject"),
                    "sentAt": sent_at.isoformat() if sent_at else None,
                    "sentBy": d.get("sentBy"),
                    "deliveryMethods": d.get("deliveryMethods"),
                    "results": d.get("results"),
                })
        except Exception:
            pass

        return {
            "threeDay": stats,
            "weekly": weekly,
            "notificationHistory": history,
        }
    except Exception as e:
        logger.error(f"Failed to get compliance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/compliance/templates/{category}")
@limiter.limit("30/minute")
def get_notification_templates(
    request: Request, category: str, user: dict = Depends(verify_firebase_token),
):
    """Get available notification templates for a category."""
    try:
        if category == "weekly":
            return {"templates": WEEKLY_REPORT_TEMPLATES, "levels": COMPLIANCE_LEVELS}
        elif category in LOW_COMPLIANCE_TEMPLATES:
            return {"templates": LOW_COMPLIANCE_TEMPLATES[category]}
        else:
            raise HTTPException(status_code=400, detail=f"Unknown category: {category}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/compliance/preview")
@limiter.limit("30/minute")
def preview_notification(
    request: Request, body: SendNotificationRequest,
    user: dict = Depends(verify_firebase_token),
):
    """Preview a notification with variables piped in (without sending)."""
    try:
        # Get participant data
        compliance = calculate_participant_compliance(body.participant_id, db, days=3)
        weekly = calculate_weekly_compliance(body.participant_id, db)

        # Get participant name from Firestore or REDCap mapping
        name = "Participant"
        p_doc = db.collection(config.col("participants")).document(body.participant_id).get()
        if p_doc.exists:
            data = p_doc.to_dict()
            name = data.get("name") or data.get("participantName") or "Participant"

        variables = {
            "name": name,
            "participant_id": body.participant_id,
            **compliance,
            **weekly,
        }

        if body.custom_subject and body.custom_body:
            return {"subject": body.custom_subject, "body": safe_format(body.custom_body, variables)}

        level = get_compliance_level(weekly["compliance_pct"]) if body.category == "weekly" else None
        idx, template = select_template(body.category, level=level,
                                         exclude_indices=[body.template_index] if body.template_index is not None else None)

        if body.template_index is not None:
            templates = (WEEKLY_REPORT_TEMPLATES.get(level, []) if body.category == "weekly"
                        else LOW_COMPLIANCE_TEMPLATES.get(body.category, []))
            if body.template_index < len(templates):
                template = templates[body.template_index]
                idx = body.template_index

        piped = pipe_template(template, variables)
        return {"templateIndex": idx, "subject": piped["subject"], "body": piped["body"], "variables": variables}
    except Exception as e:
        logger.error(f"Failed to preview notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/compliance/send")
@limiter.limit("20/minute")
def send_compliance_notification(
    request: Request, body: SendNotificationRequest,
    user: dict = Depends(verify_firebase_token),
):
    """Send a compliance notification to a participant (email and/or push)."""
    try:
        # Get participant data
        compliance = calculate_participant_compliance(body.participant_id, db, days=3)
        weekly = calculate_weekly_compliance(body.participant_id, db)

        # Get participant info
        name = "Participant"
        participant_email = None
        p_doc = db.collection(config.col("participants")).document(body.participant_id).get()
        if not p_doc.exists:
            p_doc = db.collection(config.col("valid_participants")).document(body.participant_id).get()
        if p_doc.exists:
            data = p_doc.to_dict()
            name = data.get("name") or data.get("participantName") or "Participant"
            participant_email = data.get("email") or data.get("distributionEmail")

        variables = {
            "name": name,
            "participant_id": body.participant_id,
            **compliance,
            **weekly,
        }

        # Select or use custom template
        if body.custom_subject and body.custom_body:
            subject = safe_format(body.custom_subject, variables)
            email_body = safe_format(body.custom_body, variables)
            template_idx = -1
        else:
            level = get_compliance_level(weekly["compliance_pct"]) if body.category == "weekly" else None
            idx, template = select_template(body.category, level=level)
            if body.template_index is not None:
                templates = (WEEKLY_REPORT_TEMPLATES.get(level, []) if body.category == "weekly"
                            else LOW_COMPLIANCE_TEMPLATES.get(body.category, []))
                if body.template_index < len(templates):
                    template = templates[body.template_index]
                    idx = body.template_index
            piped = pipe_template(template, variables)
            subject = piped["subject"]
            email_body = piped["body"]
            template_idx = idx

        results = {}
        sender_email = os.getenv("ALERT_SENDER_EMAIL", GRAPH_SENDER)

        # Send email (via Microsoft Graph)
        if "email" in body.delivery_methods and participant_email and graph_email_configured():
            results["email"] = send_compliance_email(
                to_email=participant_email,
                subject=subject,
                body=email_body,
                from_email=sender_email,
            )
        elif "email" in body.delivery_methods and not participant_email:
            results["email"] = {"success": False, "error": "No email address for participant"}

        # Send push notification
        if "push" in body.delivery_methods:
            # Push notification body is short (for lock screen display)
            import re
            plain_body = re.sub(r'<[^>]+>', '', email_body).replace('&amp;', '&').strip()
            push_preview = plain_body[:150] + "..." if len(plain_body) > 150 else plain_body
            results["push"] = send_push_notification(
                participant_id=body.participant_id,
                title=subject,
                body=push_preview,
                db=db,
            )
            # Also store the FULL message in the participant's received_notifications
            # so the in-app notification screen shows the complete content
            try:
                db.collection(config.col("participants")).document(body.participant_id) \
                    .collection("received_notifications").add({
                    "title": subject,
                    "body": email_body,  # Full body with HTML formatting
                    "receivedAt": datetime.utcnow(),
                    "read": False,
                    "tapped": False,
                    "source": "dashboard_compliance",
                })
            except Exception as e:
                logger.warning(f"Failed to store full notification: {e}")

        # Log to notification history
        hist_id = str(uuid.uuid4())
        db.collection(NOTIFICATION_HISTORY_COLLECTION).document(hist_id).set({
            "participantId": body.participant_id,
            "category": body.category,
            "templateIndex": template_idx,
            "subject": subject,
            "deliveryMethods": body.delivery_methods,
            "results": {k: str(v) for k, v in results.items()},
            "sentAt": datetime.utcnow(),
            "sentBy": user.get("email"),
        })

        logger.info(f"Compliance notification sent to {body.participant_id}: {body.category} by {user.get('email')}")

        return {
            "message": "Notification sent",
            "subject": subject,
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send compliance notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# REDCap Integration - Automated Participant ID Generation
# ============================================================================

import random
import requests as http_requests

REDCAP_MAPPINGS_COLLECTION = config.col("redcap_mappings")
VALID_PARTICIPANTS_COLLECTION = config.col("valid_participants")


def _send_auto_invite(participant_id: str, email: str):
    """
    Auto-send Firebase App Distribution invite to a newly qualified participant.
    Adds them as a tester for both iOS and Android — Firebase handles showing
    only the relevant platform when they open the invite.
    """
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        }

        project_number = "436153481478"

        # Step 1: Add tester
        add_url = f"https://firebaseappdistribution.googleapis.com/v1/projects/{project_number}/testers:batchAdd"
        add_resp = http_requests.post(add_url, headers=headers, json={"emails": [email]}, timeout=30)
        if add_resp.status_code not in (200, 409):
            logger.error(f"[AutoInvite] Failed to add tester {email}: {add_resp.status_code} {add_resp.text}")
            return

        # Step 2: Add to testers group
        group_url = f"https://firebaseappdistribution.googleapis.com/v1/projects/{project_number}/groups/testers"
        group_check = http_requests.get(group_url, headers=headers, timeout=30)
        if group_check.status_code == 404:
            create_url = f"https://firebaseappdistribution.googleapis.com/v1/projects/{project_number}/groups"
            http_requests.post(create_url, headers=headers, json={
                "name": f"projects/{project_number}/groups/testers",
                "displayName": "testers",
            }, timeout=30)
        http_requests.post(f"{group_url}:batchJoin", headers=headers, json={"emails": [email]}, timeout=30)

        # Update participant record with invite status
        participants_col = config.col("participants")
        db.collection(participants_col).document(participant_id).set({
            "distributionInviteSentAt": datetime.utcnow(),
            "distributionInviteStatus": "sent",
            "distributionInviteSentBy": "redcap_auto_enroll",
            "distributionEmail": email,
        }, merge=True)

        logger.info(f"[AutoInvite] Invite sent to {email} for participant {participant_id}")

    except Exception as e:
        logger.error(f"[AutoInvite] Failed to send invite to {email}: {e}", exc_info=True)


def generate_unique_9digit_id() -> str:
    """Generate a random 9-digit ID that doesn't already exist in Firestore."""
    max_attempts = 50
    for _ in range(max_attempts):
        candidate = str(random.randint(100_000_000, 999_999_999))
        doc = db.collection(VALID_PARTICIPANTS_COLLECTION).document(candidate).get()
        if not doc.exists:
            return candidate
    raise Exception("Failed to generate unique ID after maximum attempts")


def write_id_to_redcap(record_id: str, app_id: str, event_name: str = None) -> bool:
    """Write the generated app ID back to REDCap."""
    if not config.REDCAP_API_URL or not config.REDCAP_API_TOKEN:
        logger.error("REDCap API not configured")
        return False

    record_data = [{
        "record_id": record_id,
        config.REDCAP_APP_ID_FIELD: app_id,
    }]
    if event_name:
        record_data[0]["redcap_event_name"] = event_name

    resp = http_requests.post(config.REDCAP_API_URL, data={
        "token": config.REDCAP_API_TOKEN,
        "content": "record",
        "format": "json",
        "type": "flat",
        "overwriteBehavior": "normal",
        "data": json.dumps(record_data),
        "returnContent": "count",
        "returnFormat": "json",
    }, timeout=30)

    if resp.status_code == 200:
        logger.info(f"[REDCap] Wrote app ID {app_id} to record {record_id}")
        return True
    else:
        logger.error(f"[REDCap] Failed to write app ID: {resp.status_code} {resp.text}")
        return False


def generate_and_assign_app_id(redcap_record_id: str, event_name: str = None) -> dict:
    """
    Core logic: generate a unique 9-digit ID, write it to Firestore and REDCap.
    Idempotent — if this record already has an ID, returns the existing one.
    """
    # Check if this REDCap record already has an app ID (idempotent)
    mapping_ref = db.collection(REDCAP_MAPPINGS_COLLECTION).document(redcap_record_id)
    mapping_doc = mapping_ref.get()
    if mapping_doc.exists:
        existing = mapping_doc.to_dict()
        app_id = existing["app_participant_id"]
        # SELF-HEAL: the DET only calls this when REDCap's app-id field is empty,
        # yet a Firestore mapping already exists — i.e. a prior write-back failed
        # (e.g. the REDCap API token was missing). Re-write it so the ID is
        # actually visible in REDCap instead of stranded in Firestore.
        redcap_written = write_id_to_redcap(redcap_record_id, app_id, event_name)
        logger.info(f"[REDCap] Record {redcap_record_id} already mapped to {app_id}; "
                    f"re-wrote to REDCap (write: {redcap_written})")
        return {
            "status": "already_exists",
            "app_id": app_id,
            "redcap_record_id": redcap_record_id,
            "redcap_written": redcap_written,
        }

    # Generate unique 9-digit ID
    app_id = generate_unique_9digit_id()

    # Create in valid_participants collection (what the app checks during enrollment)
    db.collection(VALID_PARTICIPANTS_COLLECTION).document(app_id).set({
        "redcap_record_id": redcap_record_id,
        "created_at": datetime.utcnow(),
        "created_by": "redcap_trigger",
        "inUse": False,
    })

    # Create mapping record (REDCap record_id -> app ID)
    mapping_ref.set({
        "app_participant_id": app_id,
        "created_at": datetime.utcnow(),
        "redcap_event": event_name,
    })

    # Write the ID back to REDCap
    redcap_written = write_id_to_redcap(redcap_record_id, app_id, event_name)

    logger.info(f"[REDCap] Generated app ID {app_id} for record {redcap_record_id} (REDCap write: {redcap_written})")

    # --- Auto-enroll: fetch contact info from REDCap and register on dashboard ---
    import threading

    def auto_enroll_participant():
        try:
            # Fetch email, phone from REDCap (no event filter — these fields
            # may be in a different event than qualify_for_study)
            enroll_fields = ["subj_email", "subj_phone"]
            req_data = {
                "token": config.REDCAP_API_TOKEN,
                "content": "record",
                "format": "json",
                "records[0]": redcap_record_id,
                "returnFormat": "json",
            }
            for i, f in enumerate(enroll_fields):
                req_data[f"fields[{i}]"] = f
            resp = http_requests.post(config.REDCAP_API_URL, data=req_data, timeout=30)

            email = None
            phone = None
            if resp.status_code == 200:
                records = resp.json()
                for r in records:
                    if isinstance(r, dict):
                        email = email or (r.get("subj_email", "").strip() or None)
                        phone = phone or (r.get("subj_phone", "").strip() or None)

            # Create participants/{app_id} doc for dashboard visibility
            participants_col = config.col("participants")
            participant_data = {
                "participantId": app_id,
                "redcapRecordId": redcap_record_id,
                "createdAt": datetime.utcnow(),
                "createdBy": "redcap_auto_enroll",
                "enrolledViaRedcap": True,
            }
            if email:
                participant_data["distributionEmail"] = email
                participant_data["email"] = email
            if phone:
                participant_data["phone"] = phone
                # Digits-only normalized copy so SMS-reply matching always works
                participant_data["phoneNormalized"] = normalize_phone(phone)

            db.collection(participants_col).document(app_id).set(participant_data, merge=True)
            logger.info(f"[AutoEnroll] Participant {app_id} registered on dashboard (email={email}, phone={phone})")

            # Send Firebase App Distribution invite if we have an email
            if email:
                _send_auto_invite(app_id, email)
            else:
                logger.warning(f"[AutoEnroll] No email for {app_id} (record {redcap_record_id}), skipping invite")

        except Exception as e:
            logger.error(f"[AutoEnroll] Failed for {app_id}: {e}", exc_info=True)

    threading.Thread(target=auto_enroll_participant, daemon=True).start()

    return {
        "status": "created",
        "app_id": app_id,
        "redcap_record_id": redcap_record_id,
        "redcap_written": redcap_written,
    }


def _backfill_clinical_after_qualify(record_id, event_name, participant_id):
    """Once an app id exists for a REDCap record, backfill clinical instruments
    that may have been SAVED BEFORE qualification. The REDCap DET fires per-save,
    and the safety_plan / C-SSRS handlers drop the save when no mapping exists yet
    (mapping is created by the qualify instrument) — with no retry. If the safety
    plan was entered before the qualify form (common at the interview), it was
    silently lost. This re-syncs it (and any interview-event C-SSRS) when the
    mapping appears. Background thread; best-effort; idempotent. C-SSRS is synced
    for DISPLAY only (no alert) — live crises escalate via the real-time DET."""
    import threading

    def _run():
        try:
            _sync_safety_plan_core(participant_id, record_id, "redcap_backfill",
                                   event_name or config.REDCAP_TRIGGER_EVENT)
        except Exception as e:
            logger.error(f"[Backfill] safety plan {participant_id}/{record_id}: {e}")
        for instrument in CSSRS_INSTRUMENTS:
            try:
                sync_cssrs_from_redcap(
                    record_id=record_id, instrument=instrument,
                    event_name=event_name or config.REDCAP_TRIGGER_EVENT,
                    participant_id=participant_id, db=db, config=config, logger=logger,
                    fire_alert=False)
            except Exception as e:
                # Wrong event (e.g. weekly C-SSRS lives elsewhere) just means
                # nothing to backfill here — it syncs via its own real-time DET.
                logger.info(f"[Backfill] C-SSRS {instrument} {participant_id}: {e}")
        logger.info(f"[Backfill] Clinical backfill done for {participant_id} (record {record_id})")

    threading.Thread(target=_run, daemon=True).start()


@app.post("/api/redcap/data-entry-trigger")
@limiter.limit("60/minute")
async def redcap_data_entry_trigger(request: Request):
    """
    REDCap Data Entry Trigger endpoint.
    Called by REDCap whenever a form is saved. Handles four instruments:

    1. qualify_for_study — generates app participant ID when subject_qualified=Yes
    2. safety_plan — syncs safety plan data to Firestore on every save/revision
    3. C-SSRS Screen (weekly) — syncs to Firestore, triggers crisis alert if Q4/Q5/Q6 endorsed
    4. C-SSRS Pediatric (interview) — syncs to Firestore, triggers crisis alert if intent/plan/behavior endorsed

    This endpoint is NOT behind Firebase auth (REDCap can't send auth tokens),
    but it bypasses the IP whitelist (like the scheduler endpoint).
    """
    try:
        # REDCap sends form-encoded POST data
        import urllib.parse

        # Try reading as form data first (FastAPI may have consumed the body)
        try:
            form = await request.form()
            form_data = dict(form)
        except Exception:
            # Fallback to raw body parsing
            body = await request.body()
            form_data = dict(urllib.parse.parse_qsl(body.decode("utf-8"))) if body else {}

        logger.info(f"[REDCap DET] Raw form data keys: {list(form_data.keys())}")

        instrument = form_data.get("instrument", "")
        record_id = form_data.get("record", "")
        event_name = form_data.get("redcap_event_name", "")
        project_id = form_data.get("project_id", "")

        logger.info(
            f"[REDCap DET] Received: instrument={instrument}, record={record_id}, "
            f"event={event_name}, project={project_id}"
        )

        # This endpoint bypasses the Dartmouth IP whitelist and (because REDCap
        # calls it server-to-server, with no way to send a Firebase login) cannot
        # sit behind dashboard auth. Instead we verify the caller is our REDCap
        # project: (1) project_id must match the configured project, and
        # (2) if REDCAP_DET_SECRET is configured, a matching ?secret= must be
        # present (add it to the DET URL in REDCap project settings).
        if config.REDCAP_PROJECT_ID and project_id and str(project_id) != str(config.REDCAP_PROJECT_ID):
            logger.warning(f"[REDCap DET] Rejected: project_id {project_id} != configured {config.REDCAP_PROJECT_ID}")
            raise HTTPException(status_code=403, detail="Unrecognized project")
        det_secret = os.getenv("REDCAP_DET_SECRET")
        if det_secret:
            provided = request.query_params.get("secret") or form_data.get("secret", "")
            if provided != det_secret:
                logger.warning("[REDCap DET] Rejected: missing/invalid DET secret")
                raise HTTPException(status_code=403, detail="Invalid secret")

        # ---- Safety Plan instrument: sync to Firestore on save ----
        if instrument == "safety_plan":
            logger.info(f"[REDCap DET] Safety plan saved for record {record_id}, syncing...")

            if not config.REDCAP_API_URL or not config.REDCAP_API_TOKEN:
                raise HTTPException(status_code=500, detail="REDCap API not configured")

            # Look up the participant's app ID from the REDCap record
            mapping_doc = db.collection(REDCAP_MAPPINGS_COLLECTION).document(record_id).get()
            if not mapping_doc.exists:
                logger.warning(f"[REDCap DET] No mapping for record {record_id}, cannot sync safety plan")
                return {"status": "ignored", "reason": f"no app ID mapping for record {record_id}"}

            participant_id = mapping_doc.to_dict().get("app_participant_id")
            if not participant_id:
                return {"status": "ignored", "reason": "mapping exists but no app_participant_id"}

            # Shared core: writes the subcollection AND copies address/county/
            # emergency contacts onto the participant doc (used by the RAS + crisis
            # notifications).
            _sync_safety_plan_core(participant_id, record_id, "redcap_trigger",
                                   event_name or config.REDCAP_TRIGGER_EVENT)
            return {
                "status": "safety_plan_synced",
                "participant_id": participant_id,
                "redcap_record_id": record_id,
            }

        # ---- C-SSRS instruments: sync to Firestore + trigger crisis alerts ----
        if instrument in CSSRS_INSTRUMENTS:
            logger.info(f"[REDCap DET] C-SSRS ({instrument}) saved for record {record_id}, syncing...")

            if not config.REDCAP_API_URL or not config.REDCAP_API_TOKEN:
                raise HTTPException(status_code=500, detail="REDCap API not configured")

            mapping_doc = db.collection(REDCAP_MAPPINGS_COLLECTION).document(record_id).get()
            if not mapping_doc.exists:
                logger.warning(f"[REDCap DET] No mapping for record {record_id}, cannot sync C-SSRS")
                return {"status": "ignored", "reason": f"no app ID mapping for record {record_id}"}

            participant_id = mapping_doc.to_dict().get("app_participant_id")
            if not participant_id:
                return {"status": "ignored", "reason": "mapping exists but no app_participant_id"}

            result = sync_cssrs_from_redcap(
                record_id=record_id,
                instrument=instrument,
                event_name=event_name or config.REDCAP_TRIGGER_EVENT,
                participant_id=participant_id,
                db=db,
                config=config,
                logger=logger,
            )

            return result

        # ---- Qualifying instrument: generate app ID ----
        if instrument != config.REDCAP_TRIGGER_INSTRUMENT:
            return {"status": "ignored", "reason": f"instrument '{instrument}' is not a trigger"}

        # Verify the participant actually qualified by checking the field value in REDCap
        if not config.REDCAP_API_URL or not config.REDCAP_API_TOKEN:
            raise HTTPException(status_code=500, detail="REDCap API not configured")

        resp = http_requests.post(config.REDCAP_API_URL, data={
            "token": config.REDCAP_API_TOKEN,
            "content": "record",
            "format": "json",
            "records[0]": record_id,
            "fields[0]": config.REDCAP_TRIGGER_FIELD,
            "fields[1]": config.REDCAP_APP_ID_FIELD,
            "events[0]": event_name or config.REDCAP_TRIGGER_EVENT,
            "returnFormat": "json",
        }, timeout=30)

        if resp.status_code != 200:
            logger.error(f"[REDCap DET] Failed to fetch record: {resp.status_code} {resp.text}")
            raise HTTPException(status_code=502, detail="Failed to verify with REDCap")

        records = resp.json()
        if not records:
            return {"status": "ignored", "reason": "record not found in REDCap"}

        record_data = records[0]
        qualified_value = record_data.get(config.REDCAP_TRIGGER_FIELD, "")
        existing_app_id = record_data.get(config.REDCAP_APP_ID_FIELD, "")

        # Check if already has an app ID in REDCap
        if existing_app_id:
            logger.info(f"[REDCap DET] Record {record_id} already has app ID: {existing_app_id}")
            # Backfill clinical instruments saved before qualification (DET ordering).
            _backfill_clinical_after_qualify(record_id, event_name or config.REDCAP_TRIGGER_EVENT, existing_app_id)
            return {"status": "already_exists", "app_id": existing_app_id}

        # Check if participant qualified
        if str(qualified_value) != config.REDCAP_TRIGGER_VALUE:
            return {"status": "ignored", "reason": f"subject_qualified={qualified_value}, not triggered"}

        # Generate and assign the app ID
        result = generate_and_assign_app_id(
            redcap_record_id=record_id,
            event_name=event_name or config.REDCAP_TRIGGER_EVENT,
        )

        # Backfill clinical instruments (safety plan / C-SSRS) that the DET dropped
        # because they were saved before this app id / mapping existed.
        if result.get("app_id"):
            _backfill_clinical_after_qualify(record_id, event_name or config.REDCAP_TRIGGER_EVENT, result["app_id"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[REDCap DET] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/redcap/generate-id")
@limiter.limit("20/minute")
def admin_generate_redcap_id(
    request: Request,
    record_id: str = Query(..., description="REDCap record ID"),
    event_name: str = Query(default=None, description="REDCap event name"),
    user: dict = Depends(verify_admin_token),
):
    """
    Manually generate an app ID for a REDCap record (admin only).
    Use when the Data Entry Trigger didn't fire or for manual enrollment.
    """
    try:
        result = generate_and_assign_app_id(
            redcap_record_id=record_id,
            event_name=event_name or config.REDCAP_TRIGGER_EVENT,
        )
        logger.info(f"[REDCap] Admin {user.get('email')} generated ID for record {record_id}: {result}")
        return result
    except Exception as e:
        logger.error(f"[REDCap] Admin ID generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/redcap/mappings")
@limiter.limit("30/minute")
def get_redcap_mappings(request: Request, user: dict = Depends(verify_admin_token)):
    """Get all REDCap record -> app ID mappings (admin only)."""
    try:
        mappings = []
        for doc in db.collection(REDCAP_MAPPINGS_COLLECTION).stream():
            data = doc.to_dict()
            mappings.append({
                "redcap_record_id": doc.id,
                "app_participant_id": data.get("app_participant_id"),
                "created_at": data.get("created_at").isoformat() if data.get("created_at") else None,
                "redcap_event": data.get("redcap_event"),
            })
        return {"mappings": mappings}
    except Exception as e:
        logger.error(f"Failed to get REDCap mappings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# REDCap Safety Plan Sync
# ============================================================================

# REDCap safety_plan instrument field names → Firestore document structure
REDCAP_SAFETY_PLAN_FIELDS = [
    "sp_warning_signs_1", "sp_warning_signs_2", "sp_warning_signs_3",
    "sp_coping_1", "sp_coping_2", "sp_coping_3",
    "sp_distraction_1", "sp_distraction_1phone",
    "sp_distraction_2", "sp_distraction_2phone",
    "sp_distraction_3", "sp_distraction_4",
    "sp_support1", "sp_support1_phone",
    "sp_support2", "sp_support2_phone",
    "sp_support3", "sp_support3_phone",
    "sp_clinician_name", "sp_clinician_phone", "sp_clinician_er_contact",
    "sp_local_er_name", "sp_local_er_phone", "sp_local_er_address",
    "sp_environment1", "sp_environment2",
    "sp_reasons_live",
    "subj_county", "sp_er_service_number",
    # Interview: participant address & home type (for wellness check dispatching)
    "sp_subj_address", "subj_address_type", "participant_address_other",
]

# Home type mapping (REDCap radio choices → labels)
HOME_TYPE_MAP = {"0": "Apartment", "1": "Condo", "2": "Town house", "3": "House", "4": "Other"}


def transform_redcap_safety_plan(redcap_data: dict) -> dict:
    """
    Transform REDCap safety plan fields into the Firestore document structure
    that the Flutter app reads from participants/{id}/safety_plan/current.
    """

    def _nonempty(val):
        """Return val if it's a non-empty string, else None."""
        return val.strip() if val and val.strip() else None

    def _collect_list(*values):
        """Return list of non-empty values."""
        return [v for v in values if v]

    def _contact(name_val, phone_val):
        """Build a contact dict if at least name is present."""
        name = _nonempty(redcap_data.get(name_val, ""))
        phone = _nonempty(redcap_data.get(phone_val, ""))
        if name:
            return {"name": name, "phone": phone}
        return None

    def _place(field):
        """Build a place entry."""
        val = _nonempty(redcap_data.get(field, ""))
        if val:
            return {"name": val}
        return None

    # Step 1: Warning Signs
    warning_signs = _collect_list(
        _nonempty(redcap_data.get("sp_warning_signs_1", "")),
        _nonempty(redcap_data.get("sp_warning_signs_2", "")),
        _nonempty(redcap_data.get("sp_warning_signs_3", "")),
    )

    # Step 2: Internal Coping Strategies
    coping_strategies = _collect_list(
        _nonempty(redcap_data.get("sp_coping_1", "")),
        _nonempty(redcap_data.get("sp_coping_2", "")),
        _nonempty(redcap_data.get("sp_coping_3", "")),
    )

    # Step 3: People & Places for Distraction
    distraction_contacts = []
    for c in [
        _contact("sp_distraction_1", "sp_distraction_1phone"),
        _contact("sp_distraction_2", "sp_distraction_2phone"),
    ]:
        if c:
            distraction_contacts.append(c)

    distraction_places = []
    for p in [_place("sp_distraction_3"), _place("sp_distraction_4")]:
        if p:
            distraction_places.append(p)

    # Step 4: Support Network
    support_contacts = []
    for c in [
        _contact("sp_support1", "sp_support1_phone"),
        _contact("sp_support2", "sp_support2_phone"),
        _contact("sp_support3", "sp_support3_phone"),
    ]:
        if c:
            support_contacts.append(c)

    # Step 5: Professionals — clinician + local ER
    clinician_name = _nonempty(redcap_data.get("sp_clinician_name", ""))
    clinician_phone = _nonempty(redcap_data.get("sp_clinician_phone", ""))
    clinician_er_contact = _nonempty(redcap_data.get("sp_clinician_er_contact", ""))

    local_er_name = _nonempty(redcap_data.get("sp_local_er_name", ""))
    local_er_phone = _nonempty(redcap_data.get("sp_local_er_phone", ""))
    local_er_address = _nonempty(redcap_data.get("sp_local_er_address", ""))

    # Step 6: Environment Safety
    environment_safety = _collect_list(
        _nonempty(redcap_data.get("sp_environment1", "")),
        _nonempty(redcap_data.get("sp_environment2", "")),
    )

    # Step 7: Reasons for Living
    reasons_to_live = _nonempty(redcap_data.get("sp_reasons_live", ""))

    # Additional fields (hidden in REDCap, used by research team / app)
    county = _nonempty(redcap_data.get("subj_county", ""))
    er_service_number = _nonempty(redcap_data.get("sp_er_service_number", ""))

    # Address & home type (from interview_script_questions instrument)
    address = _nonempty(redcap_data.get("sp_subj_address", ""))
    home_type_raw = _nonempty(redcap_data.get("subj_address_type", ""))
    home_type = HOME_TYPE_MAP.get(home_type_raw, home_type_raw) if home_type_raw else None
    home_type_other = _nonempty(redcap_data.get("participant_address_other", ""))
    if home_type == "Other" and home_type_other:
        home_type = f"Other ({home_type_other})"

    return {
        "warningSigns": warning_signs,
        "copingStrategies": coping_strategies,
        "distractionContacts": distraction_contacts,
        "distractionPlaces": distraction_places,
        "supportContacts": support_contacts,
        "clinicianName": clinician_name,
        "clinicianPhone": clinician_phone,
        "clinicianErContact": clinician_er_contact,
        "localErName": local_er_name,
        "localErPhone": local_er_phone,
        "localErAddress": local_er_address,
        "environmentSafety": environment_safety,
        "reasonsToLive": reasons_to_live,
        "county": county,
        "erServiceNumber": er_service_number,
        "address": address,
        "homeType": home_type,
    }


def fetch_redcap_safety_plan(record_id: str, event_name: str = None) -> dict:
    """Fetch safety plan fields from REDCap for a given record."""
    if not config.REDCAP_API_URL or not config.REDCAP_API_TOKEN:
        raise Exception("REDCap API not configured")

    resp = http_requests.post(config.REDCAP_API_URL, data={
        "token": config.REDCAP_API_TOKEN,
        "content": "record",
        "format": "json",
        "records[0]": record_id,
        **{f"fields[{i}]": f for i, f in enumerate(REDCAP_SAFETY_PLAN_FIELDS)},
        "events[0]": event_name or config.REDCAP_TRIGGER_EVENT,
        "returnFormat": "json",
    }, timeout=30)

    if resp.status_code != 200:
        raise Exception(f"REDCap API error: {resp.status_code} {resp.text}")

    records = resp.json()
    if not records:
        raise Exception(f"No record found in REDCap for record_id={record_id}")

    return records[0]


def _sync_safety_plan_core(participant_id: str, redcap_record_id: str, synced_by: str,
                           event_name: str = None) -> dict:
    """Fetch the safety plan from REDCap, write it to participants/{id}/safety_plan/
    current, AND copy the contact fields (address/county/homeType/erServiceNumber)
    + emergency contacts (the safety-plan support network) onto the participant doc
    — which the Risk Assessment Summary and the crisis-notification functions read.

    Single source of truth shared by the DET trigger, the admin endpoint, and the
    post-qualify backfill, so all three populate the SAME fields (the DET branch
    previously only wrote the subcollection, leaving address/county/emergency
    contacts blank on the participant doc)."""
    redcap_data = fetch_redcap_safety_plan(redcap_record_id, event_name)
    safety_plan = transform_redcap_safety_plan(redcap_data)
    safety_plan["syncedAt"] = datetime.utcnow()
    safety_plan["syncedBy"] = synced_by
    safety_plan["redcapRecordId"] = redcap_record_id

    p_ref = db.collection(config.col("participants")).document(participant_id)
    p_ref.collection("safety_plan").document("current").set(safety_plan)

    participant_update = {}
    if safety_plan.get("address"):
        participant_update["address"] = safety_plan["address"]
    if safety_plan.get("homeType"):
        participant_update["homeType"] = safety_plan["homeType"]
    if safety_plan.get("county"):
        participant_update["county"] = safety_plan["county"]
    if safety_plan.get("erServiceNumber"):
        participant_update["erServiceNumber"] = safety_plan["erServiceNumber"]
    support_contacts = [c for c in (safety_plan.get("supportContacts") or []) if c.get("phone")]
    if support_contacts:
        participant_update["emergencyContacts"] = support_contacts
    if participant_update:
        p_ref.set(participant_update, merge=True)

    logger.info(f"[SafetyPlan] Synced for participant {participant_id} (REDCap {redcap_record_id}), "
                f"{sum(1 for v in safety_plan.values() if v)} fields, "
                f"{len(support_contacts)} emergency contact(s)")
    return {
        "status": "synced",
        "participant_id": participant_id,
        "redcap_record_id": redcap_record_id,
        "fields_populated": sum(1 for v in safety_plan.values() if v),
    }


@app.post("/api/admin/safety-plan/sync/{participant_id}")
@limiter.limit("30/minute")
def sync_safety_plan(
    request: Request,
    participant_id: str,
    user: dict = Depends(verify_firebase_token),
):
    """
    Fetch safety plan from REDCap and write to Firestore for a participant.
    Looks up the REDCap record_id via the redcap_mappings collection.
    """
    try:
        # Look up REDCap record_id from participant's app ID
        # Check redcap_mappings for a mapping where app_participant_id == participant_id
        mappings = list(db.collection(REDCAP_MAPPINGS_COLLECTION)
            .where("app_participant_id", "==", participant_id)
            .limit(1).stream())

        if not mappings:
            # Also check valid_participants which stores redcap_record_id
            vp_doc = db.collection(VALID_PARTICIPANTS_COLLECTION).document(participant_id).get()
            if vp_doc.exists and vp_doc.to_dict().get("redcap_record_id"):
                redcap_record_id = vp_doc.to_dict()["redcap_record_id"]
            else:
                raise HTTPException(status_code=404, detail=f"No REDCap mapping found for participant {participant_id}")
        else:
            redcap_record_id = mappings[0].id

        return _sync_safety_plan_core(participant_id, redcap_record_id, user.get("email"))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SafetyPlan] Sync failed for {participant_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/safety-plan/sync-all")
@limiter.limit("5/minute")
def sync_all_safety_plans(
    request: Request,
    user: dict = Depends(verify_admin_token),
):
    """
    Sync safety plans for ALL participants that have REDCap mappings.
    Useful for bulk initial sync or after REDCap data is updated.
    """
    try:
        results = {"synced": 0, "skipped": 0, "errors": []}
        participants_col = config.col("participants")

        for mapping_doc in db.collection(REDCAP_MAPPINGS_COLLECTION).stream():
            redcap_record_id = mapping_doc.id
            mapping_data = mapping_doc.to_dict()
            participant_id = mapping_data.get("app_participant_id")

            if not participant_id:
                results["skipped"] += 1
                continue

            try:
                redcap_data = fetch_redcap_safety_plan(redcap_record_id)
                safety_plan = transform_redcap_safety_plan(redcap_data)
                safety_plan["syncedAt"] = datetime.utcnow()
                safety_plan["syncedBy"] = user.get("email")
                safety_plan["redcapRecordId"] = redcap_record_id

                db.collection(participants_col).document(participant_id) \
                    .collection("safety_plan").document("current").set(safety_plan)

                results["synced"] += 1
            except Exception as e:
                results["errors"].append({
                    "participant_id": participant_id,
                    "redcap_record_id": redcap_record_id,
                    "error": str(e),
                })

        logger.info(
            f"[SafetyPlan] Bulk sync by {user.get('email')}: "
            f"{results['synced']} synced, {results['skipped']} skipped, "
            f"{len(results['errors'])} errors"
        )
        return results

    except Exception as e:
        logger.error(f"[SafetyPlan] Bulk sync failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# C-SSRS Sync & Risk Assessment (modular — see cssrs_sync.py, risk_assessment.py)
# ============================================================================

from cssrs_sync import (
    sync_cssrs_from_redcap, CSSRS_INSTRUMENTS,
    CSSRS_SCREEN_INSTRUMENT, CSSRS_WEEKLY_INSTRUMENT, CSSRS_PEDIATRIC_INSTRUMENT,
)
from risk_assessment import (
    register_risk_assessment_routes,
    auto_send_risk_pdf_if_needed,
)

register_risk_assessment_routes(app, db, limiter, verify_firebase_token, config, logger)


# ============================================================================
# Main entry point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
