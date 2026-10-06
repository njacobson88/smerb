"""Team-facing Slack notifications for safety events (PI-specified, 2026-10-05).

Rules:
  * Slack hears about a safety event ONLY when the automated sequence has not
    resolved it — the same moment on-call is first paged (+PRIMARY_PAGE_MIN).
    A walk-away the participant clears by replying ERROR 18 seconds in never
    reaches Slack at all. That is the intended outcome.
  * That email is ONE message, with the Risk Assessment PDF (carrying the
    crisis/safety plan) ATTACHED. This module composes it; the Cloud Function
    only decides *when*.
  * When an event Slack was told about is later resolved, Slack gets a short
    all-clear. Events Slack never heard about never generate one.
  * Wording is type-accurate. "POTENTIAL RISK — NOT confirmed" for a walk-away
    or incomplete check-in; "CONFIRMED DANGER" only when the participant said so.

The `compose_*` helpers are pure and unit tested; `send_team_alert` and
`notify_slack_resolution` do the I/O.
"""

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://socialscope-dashboard.web.app")

CONFIRMED_TYPES = {"confirmed_danger"}

ALERT_LABELS = {
    "confirmed_danger": "CONFIRMED DANGER",
    "unresolved_walkaway": "POTENTIAL RISK — NOT confirmed",
    "incomplete_checkin_fallback": "POTENTIAL RISK — NOT confirmed",
}

ALERT_SITUATION = {
    "confirmed_danger":
        "The participant CONFIRMED in the app that they are in immediate danger.",
    "unresolved_walkaway":
        "The participant gave concerning responses, then left the check-in before "
        "answering the safety question. They have NOT confirmed danger.",
    "incomplete_checkin_fallback":
        "The participant gave high-risk responses and exited the check-in before the "
        "safety question was shown. They have NOT confirmed danger.",
}

# How a resolution happened -> (subject tag, sentence). `detail` is appended
# for the staff paths (who logged it).
RESOLUTION_VIA = {
    "sms":                 ("RESOLVED", "the participant replied ERROR by text (not in crisis)"),
    "ivr_press1_error":    ("RESOLVED", "the participant pressed 1 on the automated call (not in crisis)"),
    "ivr_press3_resolved": ("RESOLVED", "the participant pressed 3 on the automated call (was in crisis, has already received support)"),
    "app_push_error":      ("RESOLVED", "the participant tapped 'error' in the app (not in crisis)"),
    "bridge_988":          ("CONNECTED TO 988", "the participant was connected to the 988 Suicide & Crisis Lifeline"),
}

DISPOSITION_LABELS = {
    "contacted_safe": "Safe",
    "contacted_needs_support": "Needs support",
    "unable_to_reach": "Unable to reach",
    "false_alarm": "False alarm",
    "escalated_988": "Escalated to 988",
    "escalated_er": "Escalated to ER",
    "crisis_resolved_with_support": "Resolved with support",
}

# Not outcomes — on-call taking the page. Never worth a Slack email.
NON_TERMINAL_DISPOSITIONS = {"acknowledged", "ongoing"}

# Audit-trail types that describe what the automated system already did.
OUTREACH_TYPES = {
    "participant_sms_sent": "Text sent",
    "participant_push_sent": "App notification sent",
    "participant_email_sent": "Email sent",
    "participant_call_initiated": "Automated call placed",
    "participant_call_failed": "Automated call FAILED",
    "participant_followup_sent": "Follow-up text/email sent",
}


def _et(ts: Any) -> str:
    """Firestore timestamp / datetime -> 'h:mm PM ET'. Blank if unknown."""
    if ts is None:
        return ""
    try:
        dt = ts if isinstance(ts, datetime) else datetime.utcfromtimestamp(ts.timestamp()).replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
    except Exception:
        return ""


def _trigger_summary(event: Dict[str, Any], alert: Optional[Dict[str, Any]]) -> str:
    """'intention_strength = 44/100' style lines for each trigger question."""
    triggers = []
    if alert and isinstance(alert.get("triggerQuestions"), list):
        triggers = [t for t in alert["triggerQuestions"] if t]
    elif event.get("triggerQuestion"):
        triggers = [t.strip() for t in str(event["triggerQuestion"]).split(",") if t.strip()]
    # Look in both: the event snapshot and the alert document can each carry
    # answers the other lacks (alert values overlay event values per key).
    responses = dict(event.get("responses") or {})
    responses.update((alert or {}).get("responses") or {})
    lines = []
    for q in triggers:
        raw = responses.get(q)
        try:
            val = f"{float(raw):.0f}/100"
        except (TypeError, ValueError):
            val = str(raw) if raw not in (None, "") else "?"
        lines.append(f"{q} = {val}")
    return "; ".join(lines) if lines else "(trigger not recorded)"


def compose_team_alert(
    event: Dict[str, Any],
    alert: Optional[Dict[str, Any]],
    audit_rows: list,
    minutes_unresolved: float,
    paged_to: Optional[str],
) -> Tuple[str, str]:
    """Subject + plain-text body for the ONE Slack email about an unresolved event."""
    pid = event.get("participantId", "?")
    alert_type = event.get("alertType") or "confirmed_danger"
    label = ALERT_LABELS.get(alert_type, "SAFETY ALERT")
    situation = ALERT_SITUATION.get(alert_type, "A participant endorsed imminent self-harm risk during check-in.")
    name = event.get("participantName")
    mins = int(round(minutes_unresolved))

    subject = f"[{label} — unresolved {mins} min] Participant {pid}"

    exceeded = _et((alert or {}).get("thresholdExceededAt"))
    created = _et(event.get("createdAt"))
    timing = []
    if exceeded:
        timing.append(f"Concerning responses at {exceeded}")
    if created:
        timing.append(f"alert created {created}")
    timing.append(f"unresolved for {mins} min")

    outreach = []
    for r in sorted(audit_rows, key=lambda x: str(x.get("loggedAt"))):
        t = r.get("type")
        if t in OUTREACH_TYPES:
            when = _et(r.get("loggedAt"))
            outreach.append(f"  • {OUTREACH_TYPES[t]}{f' {when}' if when else ''}")
    if not outreach:
        outreach.append("  • (no automated outreach recorded)")
    if not event.get("participantPhone"):
        outreach.append("  • NO PHONE ON FILE — no text or call was possible")
    if event.get("participantSmsOptedOut"):
        outreach.append("  • Participant has opted out of SMS — reach them by phone")
    outreach.append("  • No response from the participant on any channel")

    paged = (f"On-call paged now: {paged_to}." if paged_to
             else "On-call page attempted now (no primary on the roster — check the roster).")

    body = (
        f"[SocialScope {label}]\n"
        f"Participant: {pid}{f' ({name})' if name else ''}\n"
        f"{' | '.join(timing)}\n"
        f"Trigger: {_trigger_summary(event, alert)}\n\n"
        f"{situation}\n\n"
        f"What the automated system has done:\n" + "\n".join(outreach) + "\n\n"
        f"{paged} Reply ACK by text to take it; SAFE / SUPPORT / NOREACH / FALSE / 988 / ER to log the outcome.\n\n"
        f"Risk Assessment Summary (with crisis/safety plan) is attached.\n"
        f"Dashboard: {DASHBOARD_URL}\n"
        f"Alert ID: {event.get('alertId') or ''}"
    )
    return subject, body


def compose_resolution(
    event: Dict[str, Any], via: str, detail: Optional[str] = None
) -> Optional[Tuple[str, str]]:
    """Subject + body for the all-clear. None means 'this is not a resolution'."""
    pid = event.get("participantId", "?")
    name = event.get("participantName")

    if via in RESOLUTION_VIA:
        tag, how = RESOLUTION_VIA[via]
    elif via.startswith("oncall_sms:") or via.startswith("dashboard:"):
        channel, _, disp = via.partition(":")
        if disp in NON_TERMINAL_DISPOSITIONS or not disp:
            return None
        label = DISPOSITION_LABELS.get(disp, disp)
        who = detail or ("on-call" if channel == "oncall_sms" else "a team member")
        where = "by text" if channel == "oncall_sms" else "on the dashboard"
        tag = "ESCALATED" if disp in ("escalated_988", "escalated_er") else "RESOLVED"
        how = f"{who} logged the outcome \"{label}\" {where}"
    else:
        return None

    subject = f"[{tag}] Participant {pid} — {how.split(' (')[0]}"
    body = (
        f"[SocialScope {tag}]\n"
        f"Participant: {pid}{f' ({name})' if name else ''}\n"
        f"At: {_et(datetime.now(timezone.utc))}\n\n"
        f"This safety event is {('now connected to 988' if tag == 'CONNECTED TO 988' else 'resolved')}: {how}.\n\n"
        f"Dashboard: {DASHBOARD_URL}\n"
        f"Alert ID: {event.get('alertId') or ''}"
    )
    return subject, body


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def _slack_targets():
    from graph_email import graph_email_configured, GRAPH_SENDER
    slack = (os.getenv("SLACK_CHANNEL_EMAIL") or "").strip()
    sender = (os.getenv("ALERT_SENDER_EMAIL") or GRAPH_SENDER).strip()
    if not graph_email_configured() or not slack:
        return None, None
    return slack, sender


def send_team_alert(event_id: str, db, config, paged_to: Optional[str] = None) -> Dict[str, Any]:
    """Send the single Slack email (PDF attached) for an unresolved event. Idempotent."""
    from graph_email import send_graph_email
    from risk_assessment import build_risk_pdf

    ref = db.collection(config.col("safety_events")).document(event_id)
    snap = ref.get()
    if not snap.exists:
        return {"sent": False, "reason": "event_not_found"}
    event = snap.to_dict() or {}
    if event.get("teamAlertSent") is True:
        return {"sent": False, "reason": "already_sent"}

    # Claim first so a second caller (or a retry after a partial failure)
    # cannot produce two emails.
    ref.update({"teamAlertSent": True, "teamAlertSentAt": datetime.utcnow(),
                "teamAlertPagedTo": paged_to})

    slack, sender = _slack_targets()
    if not slack:
        ref.update({"teamAlertSent": False, "teamAlertError": "slack_not_configured"})
        return {"sent": False, "reason": "slack_not_configured"}

    pid = event.get("participantId")
    alert = None
    try:
        a = (db.collection(config.col("participants")).document(pid)
               .collection("safety_alerts").document(event.get("alertId") or event_id).get())
        alert = a.to_dict() if a.exists else None
    except Exception:
        pass
    audit_rows = [x.to_dict() or {} for x in ref.collection("audit_trail").stream()]

    created = event.get("createdAt")
    try:
        minutes = (datetime.utcnow() - datetime.utcfromtimestamp(created.timestamp())).total_seconds() / 60
    except Exception:
        minutes = 0.0

    subject, body = compose_team_alert(event, alert, audit_rows, minutes, paged_to)

    attachments = []
    pdf_error = None
    try:
        pdf_path, _assessment = build_risk_pdf(pid, db, config, logger, generated_by="team_alert")
        with open(pdf_path, "rb") as f:
            attachments.append({
                "name": f"risk_assessment_{pid}.pdf",
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(f.read()).decode(),
            })
    except Exception as e:
        pdf_error = str(e)
        logger.error(f"[TeamAlert] PDF build failed for {pid}: {e}", exc_info=True)
        body += "\n\n(The Risk Assessment PDF could not be generated — open the dashboard for the safety plan.)"

    try:
        send_graph_email(slack, subject, text=body, sender=sender, attachments=attachments or None)
    except Exception as e:
        logger.error(f"[TeamAlert] Slack email failed for {pid}: {e}", exc_info=True)
        ref.update({"teamAlertSent": False, "teamAlertError": str(e)})
        ref.collection("audit_trail").document().set({
            "type": "team_alert_failed", "error": str(e), "pagedTo": paged_to,
            "loggedBy": "system", "loggedAt": datetime.utcnow()})
        return {"sent": False, "reason": str(e)}

    ref.update({"teamAlertError": pdf_error, "teamAlertPdfAttached": not pdf_error})
    ref.collection("audit_trail").document().set({
        "type": "team_alert_sent", "pagedTo": paged_to, "pdfAttached": not pdf_error,
        "minutesUnresolved": round(minutes), "loggedBy": "system", "loggedAt": datetime.utcnow()})
    logger.info(f"[TeamAlert] Slack alerted for {pid} ({event.get('alertType')}, pdf={'yes' if not pdf_error else 'NO'})")
    return {"sent": True, "pdfAttached": not pdf_error}


def notify_slack_resolution(event_ref_or_id, db, config, via: str, detail: Optional[str] = None) -> Dict[str, Any]:
    """All-clear to Slack — only for events Slack was told about, and only once."""
    from graph_email import send_graph_email
    try:
        ref = (event_ref_or_id if hasattr(event_ref_or_id, "get")
               else db.collection(config.col("safety_events")).document(str(event_ref_or_id)))
        snap = ref.get()
        if not snap.exists:
            return {"sent": False, "reason": "event_not_found"}
        event = snap.to_dict() or {}
        if event.get("teamAlertSent") is not True:
            return {"sent": False, "reason": "team_never_alerted"}
        if event.get("resolutionNoticeSent") is True:
            return {"sent": False, "reason": "already_sent"}
        composed = compose_resolution(event, via, detail)
        if composed is None:
            return {"sent": False, "reason": "not_a_resolution"}

        ref.update({"resolutionNoticeSent": True, "resolutionNoticeVia": via,
                    "resolutionNoticeAt": datetime.utcnow()})
        slack, sender = _slack_targets()
        if not slack:
            return {"sent": False, "reason": "slack_not_configured"}
        subject, body = composed
        send_graph_email(slack, subject, text=body, sender=sender)
        ref.collection("audit_trail").document().set({
            "type": "resolution_notice_sent", "via": via, "detail": detail,
            "loggedBy": "system", "loggedAt": datetime.utcnow()})
        logger.info(f"[TeamAlert] Resolution notice sent for {event.get('participantId')} via {via}")
        return {"sent": True}
    except Exception as e:
        logger.error(f"[TeamAlert] Resolution notice failed ({via}): {e}", exc_info=True)
        return {"sent": False, "reason": str(e)}
