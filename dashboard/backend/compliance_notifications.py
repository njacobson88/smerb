"""
SocialScope Compliance Notification System
- Low compliance alerts (EMA + screenshots)
- Weekly gamified compliance reports
- Push notifications via Firebase Cloud Messaging
- Email via SendGrid
- Multiple message templates with piped variants
"""

import os
import random
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import sendgrid
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
import firebase_admin
from firebase_admin import firestore

import config

# ============================================================================
# Message Templates — Low Compliance (EMA / Screenshots)
# ============================================================================

LOW_COMPLIANCE_TEMPLATES = {
    "ema": [
        {
            "subject": "Quick check-in from the SocialScope team",
            "body": "Hi {name},\n\nWe noticed you've completed {ema_count} of {ema_expected} check-ins over the past few days. We know life gets busy, and we really appreciate your continued participation.\n\nEach check-in takes less than 2 minutes and helps us understand how social media affects well-being. Your responses are incredibly valuable to our research.\n\nIf you're having any trouble with the app, please don't hesitate to reach out — we're happy to help!\n\nBest,\nThe SocialScope Study Team\nDartmouth College",
        },
        {
            "subject": "We miss your check-ins!",
            "body": "Hi {name},\n\nJust a friendly note — it looks like we've missed a few of your SocialScope check-ins recently ({ema_count}/{ema_expected} completed). No worries at all! We understand that things come up.\n\nWhen you get a chance, completing your check-ins helps us build a clearer picture of how social media impacts daily life. Every response counts.\n\nThanks for being part of this important research!\n\nWarm regards,\nThe SocialScope Study Team",
        },
        {
            "subject": "Your input matters — SocialScope check-in reminder",
            "body": "Hi {name},\n\nWe wanted to touch base and let you know that your recent check-in completion has been {compliance_pct}%. We value every response you provide, and even completing one or two more check-ins per day would make a big difference.\n\nRemember, you can complete check-ins anytime by opening the SocialScope app.\n\nThank you for your dedication to this study!\n\nBest wishes,\nThe SocialScope Study Team\nDartmouth College",
        },
        {
            "subject": "A gentle reminder from SocialScope",
            "body": "Hi {name},\n\nHope you're doing well! We noticed your check-in activity has been a bit lower than usual lately ({compliance_pct}% over the past 3 days). We completely understand — everyone has busy stretches.\n\nJust a reminder that each check-in only takes about 90 seconds and helps us learn about the relationship between social media use and well-being.\n\nWe appreciate you!\n\nThe SocialScope Research Team",
        },
        {
            "subject": "Checking in with you — SocialScope",
            "body": "Hi {name},\n\nThis is a quick note to check in with you about the SocialScope study. We've noticed fewer check-ins from you recently ({ema_count}/{ema_expected}).\n\nIf you're experiencing any issues with the app or have questions about the study, we'd love to hear from you. You can reply to this email anytime.\n\nYour participation makes a real difference in understanding social media's impact on mental health.\n\nWith gratitude,\nThe SocialScope Study Team",
        },
    ],
    "screenshots": [
        {
            "subject": "SocialScope app — quick heads up",
            "body": "Hi {name},\n\nWe wanted to let you know that the SocialScope app hasn't been capturing much browsing activity recently ({screenshot_count} screenshots in the past 3 days).\n\nFor the study to work best, we need the app running while you browse Reddit and X/Twitter. Here are a few things to check:\n\n- Make sure you're browsing social media through the SocialScope app (not your regular browser)\n- Check that the app is open and running when you use social media\n\nIf you need any help, just reply to this email!\n\nThanks,\nThe SocialScope Study Team",
        },
        {
            "subject": "Making the most of SocialScope",
            "body": "Hi {name},\n\nJust a friendly reminder — the SocialScope app captures your social media browsing to help us understand content exposure patterns. We've noticed lower activity from your account recently.\n\nTo get the most out of the study, try to use the SocialScope browser when you check Reddit or X/Twitter. Every session helps!\n\nAppreciate your continued participation.\n\nBest,\nThe SocialScope Team",
        },
        {
            "subject": "Quick tip for SocialScope",
            "body": "Hi {name},\n\nHope you're having a good week! We noticed the SocialScope app hasn't been recording much browsing activity lately ({screenshot_count} captures over 3 days).\n\nA quick reminder: please use the in-app browser for your social media browsing so we can track content exposure. This is a key part of the study data.\n\nLet us know if you have any questions!\n\nThe SocialScope Research Team\nDartmouth College",
        },
    ],
}

# ============================================================================
# Weekly Report Templates — Gamified with Compliance Levels
# ============================================================================

COMPLIANCE_LEVELS = {
    "high": {"emoji": "🌟", "label": "Excellent", "threshold": 80},
    "medium": {"emoji": "👍", "label": "Good", "threshold": 50},
    "low": {"emoji": "💪", "label": "Keep Going", "threshold": 0},
}

WEEKLY_REPORT_TEMPLATES = {
    "high": [
        {
            "subject": "🌟 Your SocialScope Weekly Report — Great Week!",
            "body": "Hi {name}! 🌟\n\nHere's your weekly SocialScope summary:\n\n📊 Check-in Compliance: {compliance_pct}%\n✅ Check-ins Completed: {ema_completed}/{ema_expected}\n📸 Screenshots Captured: {screenshot_count}\n📱 Browsing Sessions: {session_count}\n\n{emoji} {compliance_label}! You're doing an amazing job keeping up with the study. Your consistent participation makes our research possible.\n\nKeep up the fantastic work! 🎉\n\nThe SocialScope Team\nDartmouth College",
        },
        {
            "subject": "🌟 Weekly Update — You're a SocialScope Star!",
            "body": "Hey {name}! 🌟\n\nYour week in SocialScope:\n\n📋 EMA Compliance: {compliance_pct}% {emoji}\n✅ {ema_completed} of {ema_expected} check-ins completed\n📸 {screenshot_count} screenshots captured\n\nYou're crushing it! Your dedication to this study is truly appreciated. Every check-in brings us closer to understanding how social media impacts well-being.\n\nSee you next week! 💙\n\nThe SocialScope Research Team",
        },
        {
            "subject": "🌟 SocialScope Report — Outstanding Participation!",
            "body": "Hi {name},\n\n🌟 Weekly Summary 🌟\n\nEMA Check-ins: {ema_completed}/{ema_expected} ({compliance_pct}%)\nScreenshots: {screenshot_count}\nBrowsing Sessions: {session_count}\n\nOutstanding work this week! You're among our most dedicated participants and your data is making a real impact on mental health research.\n\nThank you for everything you do! 🙏\n\nBest,\nThe SocialScope Team",
        },
    ],
    "medium": [
        {
            "subject": "👍 Your SocialScope Weekly Report",
            "body": "Hi {name}! 👍\n\nHere's your weekly SocialScope summary:\n\n📊 Check-in Compliance: {compliance_pct}%\n✅ Check-ins Completed: {ema_completed}/{ema_expected}\n📸 Screenshots Captured: {screenshot_count}\n\n{emoji} {compliance_label} progress! You're on the right track. Completing just a couple more check-ins each day would boost your contribution even further.\n\nEvery response matters — thank you for your participation! 💙\n\nThe SocialScope Team\nDartmouth College",
        },
        {
            "subject": "👍 Weekly SocialScope Update — Solid Progress",
            "body": "Hey {name},\n\nYour SocialScope week:\n\n📋 EMA: {compliance_pct}% ({ema_completed}/{ema_expected})\n📸 Screenshots: {screenshot_count}\n\nNice work! You're making a meaningful contribution. A small boost in daily check-ins would take your participation to the next level.\n\nThanks for sticking with us! 🤝\n\nThe SocialScope Research Team",
        },
    ],
    "low": [
        {
            "subject": "💪 Your SocialScope Weekly Report — We Believe in You!",
            "body": "Hi {name},\n\nHere's your weekly SocialScope summary:\n\n📊 Check-in Compliance: {compliance_pct}%\n✅ Check-ins Completed: {ema_completed}/{ema_expected}\n📸 Screenshots Captured: {screenshot_count}\n\n{emoji} We know life gets busy, and we appreciate every check-in you complete. Even small increases in participation make a big difference for our research.\n\nReminder: Check-ins take less than 2 minutes and can be done anytime through the app.\n\nWe're here if you need any help! 💙\n\nThe SocialScope Team\nDartmouth College",
        },
        {
            "subject": "💪 Weekly Update — Every Check-in Counts!",
            "body": "Hey {name},\n\nYour SocialScope week:\n\n📋 EMA: {compliance_pct}% ({ema_completed}/{ema_expected})\n📸 Screenshots: {screenshot_count}\n\nWe appreciate your continued participation! We know it can be tough to keep up. Just opening the app and completing one check-in a day would be a great step.\n\nYou've got this! 💪\n\nThe SocialScope Research Team",
        },
    ],
}


# ============================================================================
# Template Selection & Variable Piping
# ============================================================================

def get_compliance_level(pct: float) -> str:
    """Get compliance level string from percentage."""
    if pct >= COMPLIANCE_LEVELS["high"]["threshold"]:
        return "high"
    elif pct >= COMPLIANCE_LEVELS["medium"]["threshold"]:
        return "medium"
    return "low"


def pipe_template(template: dict, variables: dict) -> dict:
    """Replace {variable} placeholders in template with actual values."""
    result = {}
    for key, value in template.items():
        if isinstance(value, str):
            result[key] = value.format(**variables)
        else:
            result[key] = value
    return result


def select_template(category: str, level: str = None, exclude_indices: list = None) -> tuple:
    """Select a random template from the category, avoiding recently used ones."""
    if category == "weekly":
        templates = WEEKLY_REPORT_TEMPLATES.get(level, WEEKLY_REPORT_TEMPLATES["medium"])
    else:
        templates = LOW_COMPLIANCE_TEMPLATES.get(category, LOW_COMPLIANCE_TEMPLATES["ema"])

    if exclude_indices:
        available = [(i, t) for i, t in enumerate(templates) if i not in exclude_indices]
        if not available:
            available = list(enumerate(templates))
    else:
        available = list(enumerate(templates))

    idx, template = random.choice(available)
    return idx, template


# ============================================================================
# Send Notification (Email + Push)
# ============================================================================

def send_compliance_email(
    to_email: str,
    subject: str,
    body: str,
    sendgrid_api_key: str,
    from_email: str = "Social.Media.Wellness@dartmouth.edu",
) -> dict:
    """Send a compliance notification email via SendGrid."""
    try:
        sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
        message = Mail(
            from_email=(from_email, "SocialScope Study Team"),
            to_emails=to_email,
            subject=subject,
            plain_text_content=body,
        )
        response = sg.send(message)
        return {"status": response.status_code, "success": response.status_code in (200, 201, 202)}
    except Exception as e:
        return {"status": 0, "success": False, "error": str(e)}


def send_push_notification(
    participant_id: str,
    title: str,
    body: str,
    db,
) -> dict:
    """Send a push notification to a participant via Firebase Cloud Messaging REST API."""
    try:
        import google.auth
        import google.auth.transport.requests
        import requests as http_req

        # Look up the participant's FCM token from Firestore
        doc = db.collection(config.col("participants")).document(participant_id).get()
        if not doc.exists:
            return {"success": False, "error": "Participant not found"}

        data = doc.to_dict()
        fcm_token = data.get("fcmToken")

        if not fcm_token:
            return {"success": False, "error": "No FCM token registered for this participant"}

        # Use the FCM v1 REST API directly with cloud-platform scope
        # This works on Cloud Run where firebase_admin.messaging may fail
        creds, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())

        project_id = config.FIREBASE_PROJECT_ID
        url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

        resp = http_req.post(url, headers={
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        }, json={
            "message": {
                "token": fcm_token,
                "notification": {
                    "title": title,
                    "body": body,
                },
            }
        })

        if resp.status_code == 200:
            return {"success": True, "messageId": resp.json().get("name")}
        else:
            return {"success": False, "error": f"FCM API {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# Compliance Calculation
# ============================================================================

def calculate_participant_compliance(participant_id: str, db, days: int = 3) -> dict:
    """Calculate a participant's compliance over the past N days."""
    now = datetime.utcnow()
    start = now - timedelta(days=days)
    ema_expected = days * config.EMA_PROMPTS_PER_DAY

    participant_ref = db.collection(config.col("participants")).document(participant_id)

    # Count EMA responses
    ema_count = 0
    try:
        ema_query = participant_ref.collection("ema_responses").where(
            "completedAt", ">=", start
        ).where("completedAt", "<", now)
        ema_count = len(list(ema_query.stream()))
    except Exception:
        pass

    # Count screenshots
    screenshot_count = 0
    try:
        events_query = participant_ref.collection("events").where(
            "timestamp", ">=", start
        ).where("timestamp", "<", now)
        for event_doc in events_query.stream():
            event = event_doc.to_dict()
            if event.get("eventType") == "screenshot" or event.get("type") == "screenshot":
                screenshot_count += 1
    except Exception:
        pass

    compliance_pct = round((ema_count / ema_expected * 100) if ema_expected > 0 else 0, 1)

    return {
        "ema_count": ema_count,
        "ema_expected": ema_expected,
        "screenshot_count": screenshot_count,
        "compliance_pct": compliance_pct,
        "days": days,
        "needs_notification": compliance_pct < 50,
    }


def calculate_weekly_compliance(participant_id: str, db) -> dict:
    """Calculate a participant's compliance for the past week (for weekly report)."""
    now = datetime.utcnow()
    week_start = now - timedelta(days=7)
    ema_expected = 7 * config.EMA_PROMPTS_PER_DAY

    participant_ref = db.collection(config.col("participants")).document(participant_id)

    ema_count = 0
    try:
        ema_query = participant_ref.collection("ema_responses").where(
            "completedAt", ">=", week_start
        ).where("completedAt", "<", now)
        ema_count = len(list(ema_query.stream()))
    except Exception:
        pass

    screenshot_count = 0
    session_count = 0
    try:
        events_query = participant_ref.collection("events").where(
            "timestamp", ">=", week_start
        ).where("timestamp", "<", now)
        sessions = set()
        for event_doc in events_query.stream():
            event = event_doc.to_dict()
            if event.get("eventType") == "screenshot" or event.get("type") == "screenshot":
                screenshot_count += 1
            session_id = event.get("sessionId")
            if session_id:
                sessions.add(session_id)
        session_count = len(sessions)
    except Exception:
        pass

    compliance_pct = round((ema_count / ema_expected * 100) if ema_expected > 0 else 0, 1)
    level = get_compliance_level(compliance_pct)
    level_info = COMPLIANCE_LEVELS[level]

    return {
        "ema_completed": ema_count,
        "ema_expected": ema_expected,
        "screenshot_count": screenshot_count,
        "session_count": session_count,
        "compliance_pct": compliance_pct,
        "level": level,
        "emoji": level_info["emoji"],
        "compliance_label": level_info["label"],
    }
