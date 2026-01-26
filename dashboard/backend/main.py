# SocialScope Dashboard Backend
# FastAPI application with Dartmouth IP whitelisting

import os
import json
import uuid
import zipfile
import logging
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional
from ipaddress import ip_address, ip_network
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

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

# FastAPI app
app = FastAPI(
    title="SocialScope Dashboard API",
    description="Monitoring dashboard for SocialScope social media research study",
    version="1.0.0"
)

# CORS configuration
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    # Production Firebase Hosting URLs
    "https://socialscope-dashboard.web.app",
    "https://socialscope-dashboard.firebaseapp.com",
    "https://r01-redditx-suicide.web.app",
    "https://r01-redditx-suicide.firebaseapp.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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
DASHBOARD_USERS_COLLECTION = "dashboard_users"


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


@app.get("/api/debug/day-test/{participant_id}/{date}")
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


@app.get("/api/debug/participant-data/{participant_id}")
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


@app.get("/api/debug/participants-test")
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


@app.get("/api/debug/collections")
def debug_collections():
    """Debug endpoint to check Firestore connectivity."""
    try:
        # List all documents in participants collection
        participants_ref = db.collection("participants")
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
            valid_ref = db.collection("valid_participants")
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
        test2_ref = db.collection("participants").document("test2")
        test2_doc = test2_ref.get()
        result["test2_exists"] = test2_doc.exists
        if test2_doc.exists:
            result["test2_data"] = test2_doc.to_dict()

        # Check if test2 has subcollections
        try:
            test2_events = list(test2_ref.collection("events").limit(5).stream())
            result["test2_events_count"] = len(test2_events)
        except Exception:
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
    for collection_name in ["participants", "valid_participants"]:
        collection_ref = db.collection(collection_name)
        for doc in collection_ref.stream():
            if doc.id in seen_ids:
                continue

            data = doc.to_dict()

            # Filter to only enrolled participants if requested
            if enrolled_only:
                is_enrolled = (
                    data.get("inUse") == True or
                    data.get("enrolledAt") is not None or
                    data.get("lastEnrolledAt") is not None
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
    doc = db.collection("participants").document(participant_id).get()
    if doc.exists:
        return doc.to_dict()

    # Try valid_participants collection
    doc = db.collection("valid_participants").document(participant_id).get()
    if doc.exists:
        return doc.to_dict()

    return None


def get_participant_ref(participant_id: str):
    """
    Get reference for participant's subcollections (events, ema_responses, safety_alerts).
    These are always stored under participants/{id}/ regardless of where the metadata is.
    """
    return db.collection("participants").document(participant_id)


# ============================================================================
# Dashboard Cache for Scalability
# ============================================================================

DASHBOARD_CACHE_COLLECTION = "dashboard_cache"


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
    except Exception:
        pass

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
                    except:
                        responses = {}

                for key, value in responses.items():
                    if isinstance(value, str) and value.lower() in ("yes", "true"):
                        if "crisis" in key.lower() or "harm" in key.lower() or "hurt" in key.lower():
                            daily_status[checkin_date]["crisis_indicated"] = True
    except Exception:
        pass

    return dict(daily_status)


@app.post("/api/admin/refresh-cache")
def refresh_dashboard_cache(user: dict = Depends(verify_admin_token)):
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
def get_cache_status(user: dict = Depends(verify_firebase_token)):
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
def get_participants(user: dict = Depends(verify_firebase_token)):
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
                except:
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
def get_overall_status(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
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

                results.append({
                    "id": p.get("id"),
                    "study_start_date": p.get("study_start_date"),
                    "dailyStatus": filtered_daily,
                    "weeklyScreenshots": total_screenshots,
                    "weeklyCheckins": total_checkins,
                    "weeklyReddit": total_reddit,
                    "weeklyTwitter": total_twitter,
                    "overallCompliance": min(100, int((total_checkins / (days_count * config.EMA_PROMPTS_PER_DAY)) * 100)) if days_count > 0 else 0,
                })

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

            results.append({
                "id": pid,
                "study_start_date": study_start.strftime("%Y-%m-%d") if study_start else None,
                "dailyStatus": daily_list,
                "weeklyScreenshots": total_screenshots,
                "weeklyCheckins": total_checkins,
                "weeklyReddit": total_reddit,
                "weeklyTwitter": total_twitter,
                "overallCompliance": min(100, int((total_checkins / (days_count * config.EMA_PROMPTS_PER_DAY)) * 100)) if days_count > 0 else 0,
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
def get_safety_alerts(user: dict = Depends(verify_firebase_token)):
    """
    Get all safety alerts from cached data (fast).
    Returns alerts aggregated from the dashboard cache.
    """
    try:
        # Read from cache for fast response
        cache_ref = db.collection(DASHBOARD_CACHE_COLLECTION).document("overall_status")
        cache_doc = cache_ref.get()

        alerts = []

        if cache_doc.exists:
            cache_data = cache_doc.to_dict()
            cached_participants = cache_data.get("participants", [])
            refreshed_at = cache_data.get("refreshedAt")

            if refreshed_at and hasattr(refreshed_at, 'timestamp'):
                refreshed_at = datetime.fromtimestamp(refreshed_at.timestamp())

            # Extract alerts from cached daily status
            for p in cached_participants:
                pid = p.get("id")
                daily_status = p.get("dailyStatus", [])

                for day in daily_status:
                    alert_count = day.get("safety_alerts", 0)
                    if alert_count > 0:
                        alerts.append({
                            "participantId": pid,
                            "date": day.get("date"),
                            "count": alert_count,
                            "crisis_indicated": day.get("crisis_indicated", False),
                        })

            # Sort by date descending
            alerts.sort(key=lambda x: x.get("date", ""), reverse=True)

            return {
                "alerts": alerts,
                "fromCache": True,
                "refreshedAt": (refreshed_at.isoformat() + "Z") if refreshed_at else None,
            }

        # Fallback: compute live (slower)
        logger.warning("Cache miss for safety-alerts - computing live")

        participants_info = get_all_participant_ids(enrolled_only=True)

        for p_info in participants_info:
            pid = p_info["id"]
            participant_ref = get_participant_ref(pid)

            try:
                alerts_ref = participant_ref.collection("safety_alerts")
                for alert_doc in alerts_ref.stream():
                    alert = alert_doc.to_dict()
                    triggered_at = alert.get("triggeredAt")
                    if triggered_at:
                        if hasattr(triggered_at, 'timestamp'):
                            alert_date = datetime.fromtimestamp(triggered_at.timestamp()).strftime("%Y-%m-%d")
                        else:
                            alert_date = triggered_at.strftime("%Y-%m-%d")

                        alerts.append({
                            "participantId": pid,
                            "date": alert_date,
                            "count": 1,
                        })
            except Exception:
                continue

        # Aggregate alerts by participant and date
        aggregated = {}
        for a in alerts:
            key = f"{a['participantId']}_{a['date']}"
            if key in aggregated:
                aggregated[key]["count"] += 1
            else:
                aggregated[key] = a

        alerts = list(aggregated.values())
        alerts.sort(key=lambda x: x.get("date", ""), reverse=True)

        return {
            "alerts": alerts,
            "fromCache": False,
            "message": "Computed live - cache not available",
        }

    except Exception as e:
        logger.error(f"Failed to get safety alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/participant/{participant_id}/summary")
def get_participant_summary(participant_id: str, user: dict = Depends(verify_firebase_token)):
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

        enrolled_at = participant_data.get("enrolledAt") or participant_data.get("lastEnrolledAt")

        if enrolled_at:
            if hasattr(enrolled_at, 'timestamp'):
                study_start = datetime.fromtimestamp(enrolled_at.timestamp())
            else:
                study_start = enrolled_at
        else:
            study_start = datetime.now() - timedelta(days=30)

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
                        except:
                            responses = {}

                    # Check for crisis indicator in responses
                    for key, value in responses.items():
                        if isinstance(value, str) and value.lower() in ("yes", "true"):
                            if "crisis" in key.lower() or "harm" in key.lower() or "hurt" in key.lower():
                                if "crisis_indicated" not in daily_summaries[checkin_date]:
                                    daily_summaries[checkin_date]["crisis_indicated"] = False
                                daily_summaries[checkin_date]["crisis_indicated"] = True
        except Exception:
            pass

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
        except Exception:
            pass

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

        return {
            "participant_id": participant_id,
            "study_start_date": study_start.strftime("%Y-%m-%d"),
            "device_model": participant_data.get("deviceModel"),
            "os_version": participant_data.get("osVersion"),
            "daily_summary": summary_list
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get participant summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/participant/{participant_id}/day/{date}")
def get_day_detail(participant_id: str, date: str, user: dict = Depends(verify_firebase_token)):
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
                    except:
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
                            except:
                                responses = {}
                        ema_by_session[session_id] = responses
            except Exception:
                pass

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
                    except:
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


def get_storage_bucket():
    """Get Firebase Storage bucket."""
    try:
        return fb_storage.bucket(f"{config.FIREBASE_PROJECT_ID}.firebasestorage.app")
    except Exception:
        return fb_storage.bucket(f"{config.FIREBASE_PROJECT_ID}.appspot.com")


# Export Jobs Collection for async exports
EXPORT_JOBS_COLLECTION = "export_jobs"


def send_export_email(email: str, participant_id: str, download_url: str, filename: str):
    """Send email notification when export is complete using SendGrid."""
    sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
    if not sendgrid_api_key:
        logger.warning("SENDGRID_API_KEY not configured - email not sent")
        return False

    try:
        response = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {sendgrid_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": email}]}],
                "from": {"email": "noreply@socialscope-dashboard.web.app", "name": "SocialScope Dashboard"},
                "subject": f"SocialScope Export Ready: {participant_id}",
                "content": [{
                    "type": "text/html",
                    "value": f"""
                    <h2>Your SocialScope Export is Ready</h2>
                    <p>Your data export for participant <strong>{participant_id}</strong> has completed.</p>
                    <p><strong>Filename:</strong> {filename}</p>
                    <p><a href="{download_url}" style="background-color: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Download Export</a></p>
                    <p style="color: #666; font-size: 12px;">This link will expire in 48 hours.</p>
                    <hr>
                    <p style="color: #999; font-size: 11px;">SocialScope Research Dashboard - Dartmouth College</p>
                    """
                }],
            },
            timeout=10,
        )
        if response.status_code in (200, 202):
            logger.info(f"Export email sent to {email}")
            return True
        else:
            logger.error(f"SendGrid error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send export email: {e}")
        return False


def run_background_export(job_id: str, participant_id: str, export_level: int,
                          start_date: Optional[str], end_date: Optional[str],
                          user_email: str):
    """Background thread function to run export and update job status."""
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
                        except:
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
            except Exception:
                pass

            # Level 2+: Export events
            if export_level >= 2:
                events_ref = participant_ref.collection("events")
                if start_date and end_date:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                    events_query = events_ref.where("timestamp", ">=", start_dt).where("timestamp", "<", end_dt)
                else:
                    events_query = events_ref

                events_data = []
                screenshot_urls = []

                for event_doc in events_query.stream():
                    event = event_doc.to_dict()
                    for ts_field in ["timestamp", "capturedAt", "createdAt", "syncedAt"]:
                        ts_val = event.get(ts_field)
                        if ts_val and hasattr(ts_val, 'timestamp'):
                            event[ts_field] = datetime.fromtimestamp(ts_val.timestamp()).isoformat()

                    if export_level >= 3:
                        screenshot_url = event.get("screenshotUrl")
                        if screenshot_url:
                            screenshot_urls.append({
                                "event_id": event_doc.id,
                                "url": screenshot_url,
                                "timestamp": event.get("timestamp"),
                            })

                    events_data.append({"id": event_doc.id, **event})

                if events_data:
                    zf.writestr("events.json", json.dumps(events_data, indent=2, default=str))

                # Level 3: Download screenshots
                if export_level >= 3 and screenshot_urls:
                    total = len(screenshot_urls)
                    job_ref.update({"screenshotTotal": total, "screenshotProgress": 0})

                    for idx, ss_info in enumerate(screenshot_urls):
                        try:
                            url = ss_info["url"]
                            if url and url.startswith("http"):
                                response = requests.get(url, timeout=30)
                                if response.status_code == 200:
                                    ext = ".jpg"
                                    if ".png" in url.lower():
                                        ext = ".png"

                                    ts_val = ss_info.get("timestamp")
                                    if ts_val:
                                        if hasattr(ts_val, 'isoformat'):
                                            ts = ts_val.isoformat().replace(":", "-").replace("T", "_")[:19]
                                        else:
                                            ts = str(ts_val).replace(":", "-").replace("T", "_")[:19]
                                    else:
                                        ts = f"img_{idx}"

                                    filename = f"screenshots/{ts}_{ss_info['event_id'][:8]}{ext}"
                                    zf.writestr(filename, response.content)

                            # Update progress every 10 screenshots
                            if idx % 10 == 0:
                                job_ref.update({"screenshotProgress": idx + 1})

                        except Exception as e:
                            logger.warning(f"Failed to download screenshot {idx}: {e}")

        # Generate filename and store result
        level_names = {1: "meta", 2: "ocr", 3: "full"}
        filename = f"socialscope_export_{participant_id}_L{export_level}_{level_names.get(export_level, 'meta')}"
        if start_date and end_date:
            filename += f"_{start_date}_to_{end_date}"
        filename += ".zip"

        download_url = f"https://socialscope-dashboard-api-436153481478.us-central1.run.app/api/exports/{export_id}"

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

        # Send email notification
        if user_email:
            send_export_email(user_email, participant_id, download_url, filename)

        logger.info(f"Background export completed: {job_id}")

    except Exception as e:
        logger.error(f"Background export failed: {e}", exc_info=True)
        job_ref.update({
            "status": "failed",
            "error": str(e),
            "completedAt": datetime.utcnow(),
        })


@app.get("/api/export/estimate")
def estimate_export(
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
                # Estimate ~200KB per screenshot
                total_screenshot_size += 200 * 1024

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
def start_async_export(
    request: AsyncExportRequest,
    user: dict = Depends(verify_firebase_token),
):
    """
    Start an asynchronous export job for large exports (Level 3 with screenshots).
    Returns immediately with a job ID. Client can poll for status or receive email notification.
    """
    try:
        # Validate participant exists
        participant_data = get_participant_data(request.participant_id)
        participant_ref = get_participant_ref(request.participant_id)

        if not participant_data:
            events_check = list(participant_ref.collection("events").limit(1).stream())
            if not events_check:
                raise HTTPException(status_code=404, detail="Participant not found")

        # Create job document
        job_id = uuid.uuid4().hex
        job_ref = db.collection(EXPORT_JOBS_COLLECTION).document(job_id)

        user_email = request.notify_email or user.get("email")

        job_ref.set({
            "jobId": job_id,
            "participantId": request.participant_id,
            "exportLevel": request.export_level,
            "startDate": request.start_date,
            "endDate": request.end_date,
            "status": "pending",
            "createdAt": datetime.utcnow(),
            "createdBy": user.get("email"),
            "notifyEmail": user_email,
        })

        # Start background thread
        thread = threading.Thread(
            target=run_background_export,
            args=(job_id, request.participant_id, request.export_level,
                  request.start_date, request.end_date, user_email),
            daemon=True
        )
        thread.start()

        return {
            "jobId": job_id,
            "status": "pending",
            "message": "Export started. You will receive an email when complete, or check status at /api/export/jobs/{jobId}",
            "statusUrl": f"/api/export/jobs/{job_id}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start async export: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export/jobs")
def get_user_export_jobs(user: dict = Depends(verify_firebase_token)):
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
def get_export_job_status(
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


@app.get("/api/export")
def export_participant_data(
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
                        except:
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
            except Exception:
                pass

            # Level 2+: Export events with OCR data
            if export_level >= 2:
                events_ref = participant_ref.collection("events")

                if start_date and end_date:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                    events_query = events_ref.where(
                        "timestamp", ">=", start_dt
                    ).where(
                        "timestamp", "<", end_dt
                    ).order_by("timestamp")
                else:
                    events_query = events_ref.order_by("timestamp")

                events_data = []
                screenshot_urls = []  # For level 3

                for event_doc in events_query.stream():
                    event = event_doc.to_dict()
                    for ts_field in ["timestamp", "capturedAt", "createdAt", "syncedAt"]:
                        ts_val = event.get(ts_field)
                        if ts_val and hasattr(ts_val, 'timestamp'):
                            event[ts_field] = datetime.fromtimestamp(ts_val.timestamp()).isoformat()

                    # Collect screenshot URLs for level 3
                    if export_level >= 3:
                        screenshot_url = event.get("screenshotUrl")
                        if screenshot_url:
                            screenshot_urls.append({
                                "event_id": event_doc.id,
                                "url": screenshot_url,
                                "timestamp": event.get("timestamp"),
                            })

                    events_data.append({"id": event_doc.id, **event})

                if events_data:
                    zf.writestr("events.json", json.dumps(events_data, indent=2, default=str))

                # Level 3: Download and include screenshots
                if export_level >= 3 and screenshot_urls:
                    logger.info(f"Downloading {len(screenshot_urls)} screenshots for export")
                    import requests
                    from urllib.parse import unquote

                    for idx, ss_info in enumerate(screenshot_urls):
                        try:
                            url = ss_info["url"]

                            # Firebase Storage download URLs can be fetched directly
                            # URL format: https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{path}?alt=media&token={token}
                            if url and url.startswith("http"):
                                response = requests.get(url, timeout=30)
                                if response.status_code == 200:
                                    img_data = response.content
                                    # Determine file extension from URL or content-type
                                    ext = ".jpg"
                                    if ".png" in url.lower():
                                        ext = ".png"
                                    elif response.headers.get("content-type", "").startswith("image/png"):
                                        ext = ".png"

                                    # Use timestamp for filename
                                    ts_val = ss_info.get("timestamp")
                                    if ts_val:
                                        if hasattr(ts_val, 'isoformat'):
                                            ts = ts_val.isoformat().replace(":", "-").replace("T", "_")[:19]
                                        else:
                                            ts = str(ts_val).replace(":", "-").replace("T", "_")[:19]
                                    else:
                                        ts = f"img_{idx}"

                                    filename = f"screenshots/{ts}_{ss_info['event_id'][:8]}{ext}"
                                    zf.writestr(filename, img_data)
                                    logger.info(f"Downloaded screenshot {idx+1}/{len(screenshot_urls)}: {filename}")
                                else:
                                    logger.warning(f"Failed to download screenshot {idx}: HTTP {response.status_code}")
                        except Exception as e:
                            logger.warning(f"Failed to download screenshot {idx}: {e}")

        level_names = {1: "meta", 2: "ocr", 3: "full"}
        filename = f"socialscope_export_{participant_id}_L{export_level}_{level_names.get(export_level, 'meta')}"
        if start_date and end_date:
            filename += f"_{start_date}_to_{end_date}"
        filename += ".zip"

        EXPORT_INDEX[export_id] = {
            "filename": filename,
            "created_at": datetime.now().timestamp()
        }

        return {
            "download_url": f"/api/exports/{export_id}",
            "filename": filename
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/exports/{export_id}")
def download_export(export_id: str):
    """Download an export file."""
    export_path = EXPORT_DIR / f"{export_id}.zip"

    if not export_path.exists():
        raise HTTPException(status_code=404, detail="Export not found")

    meta = EXPORT_INDEX.get(export_id, {})
    filename = meta.get("filename", f"{export_id}.zip")

    return FileResponse(
        export_path,
        media_type="application/zip",
        filename=filename
    )


# ============================================================================
# Admin User Management Endpoints
# ============================================================================

class AddUserRequest(BaseModel):
    email: str
    role: str = "user"


class UpdateUserRequest(BaseModel):
    role: str


@app.get("/api/admin/users")
def get_all_users(user: dict = Depends(verify_admin_token)):
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
def add_user(request: AddUserRequest, user: dict = Depends(verify_admin_token)):
    """Add a new authorized user (admin only)."""
    try:
        email = request.email.lower().strip()
        role = request.role.lower()

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
def update_user_role(email: str, request: UpdateUserRequest, user: dict = Depends(verify_admin_token)):
    """Update a user's role (admin only)."""
    try:
        email = email.lower().strip()
        role = request.role.lower()

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
def remove_user(email: str, user: dict = Depends(verify_admin_token)):
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
# Alert Recipients Management (for Twilio SMS alerts)
# ============================================================================

ALERT_RECIPIENTS_COLLECTION = "alert_recipients"


class AddRecipientRequest(BaseModel):
    phone: str
    name: Optional[str] = None


@app.get("/api/admin/alert-recipients")
def get_alert_recipients(user: dict = Depends(verify_admin_token)):
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
def add_alert_recipient(request: AddRecipientRequest, user: dict = Depends(verify_admin_token)):
    """Add a new safety alert SMS recipient (admin only)."""
    try:
        # Clean phone number (keep only digits)
        phone = ''.join(filter(str.isdigit, request.phone))

        if len(phone) != 10:
            raise HTTPException(status_code=400, detail="Phone must be a 10-digit US number")

        # Check if already exists
        recipient_ref = db.collection(ALERT_RECIPIENTS_COLLECTION).document(phone)
        if recipient_ref.get().exists:
            raise HTTPException(status_code=400, detail="This phone number is already registered")

        # Add recipient
        recipient_ref.set({
            "phone": phone,
            "name": request.name.strip() if request.name else None,
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
def remove_alert_recipient(phone: str, user: dict = Depends(verify_admin_token)):
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
def initialize_admin():
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
# Main entry point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
