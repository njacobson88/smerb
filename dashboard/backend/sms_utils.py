"""Pure classification of inbound SMS bodies.

Kept import-free so the safety-relevant routing (what counts as a false-alarm
"error" reply, a carrier opt-out, or an on-call disposition command) is unit
tested standalone. main.py owns the Firestore/Twilio I/O and the logging.
"""

# Participant reply that means "my earlier alert was accidental" → stop escalation.
PARTICIPANT_ERROR_KEYWORDS = {
    "ERROR", "1", "ONE", "FALSE", "MISTAKE", "ACCIDENT", "ACCIDENTAL",
}

# Carrier-level opt-out / help keywords. Twilio auto-handles these for
# compliance, but we must DETECT them: a participant who texts STOP stops
# receiving ALL future SMS — including crisis-escalation texts — so the study
# team has to know the participant is now unreachable by SMS.
OPTOUT_KEYWORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "REVOKE"}
RESUBSCRIBE_KEYWORDS = {"START", "YES", "UNSTOP"}
HELP_KEYWORDS = {"HELP", "INFO"}

# On-call staff disposition commands.
SMS_DISPOSITION_MAP = {
    "ACK": "acknowledged",
    "SAFE": "contacted_safe",
    "SUPPORT": "contacted_needs_support",
    "NOREACH": "unable_to_reach",
    "FALSE": "false_alarm",
    "ERROR": "false_alarm",
    "1": "false_alarm",
    "988": "escalated_988",
    "ER": "escalated_er",
    "ONGOING": "ongoing",
}


def first_token_upper(body) -> str:
    """First whitespace-delimited token, upper-cased. '' for empty/None."""
    if not body:
        return ""
    parts = str(body).strip().upper().split()
    return parts[0] if parts else ""


def is_participant_error_reply(body) -> bool:
    """True if a participant's reply signals the alert was accidental."""
    if not body:
        return False
    up = str(body).strip().upper()
    return first_token_upper(body) in PARTICIPANT_ERROR_KEYWORDS or up in PARTICIPANT_ERROR_KEYWORDS


def is_optout(body) -> bool:
    return first_token_upper(body) in OPTOUT_KEYWORDS


def is_resubscribe(body) -> bool:
    return first_token_upper(body) in RESUBSCRIBE_KEYWORDS


def parse_oncall_command(body):
    """Return the disposition for an on-call command, or None if unrecognized."""
    return SMS_DISPOSITION_MAP.get(first_token_upper(body))


# Twilio message error codes worth explaining in plain language to coordinators.
_SMS_ERROR_REASONS = {
    "30007": "carrier filtered the message (toll-free verification likely needed)",
    "30003": "unreachable destination (phone off/out of service)",
    "30005": "unknown/invalid number",
    "30006": "landline or unreachable carrier",
    "30008": "carrier could not deliver (unknown reason)",
    "21610": "recipient has opted out (texted STOP)",
    "21408": "number not enabled / region not permitted",
    "21211": "invalid 'To' phone number",
}

# Terminal failure statuses vs. in-flight ones.
_SMS_FAILED = {"undelivered", "failed"}
_SMS_INFLIGHT = {"queued", "accepted", "scheduled", "sending", "sent"}


def describe_sms_status(status, error_code=None):
    """Plain-language delivery status for the dashboard. 'sent' is deliberately
    shown as in-flight (not success) — only 'delivered' is confirmed receipt."""
    s = (status or "").strip().lower()
    code = str(error_code or "").strip()
    if s == "delivered":
        return "Delivered"
    if s in _SMS_FAILED:
        reason = _SMS_ERROR_REASONS.get(code)
        if reason:
            return f"Not delivered — {reason}"
        return f"Not delivered (error {code})" if code else "Not delivered"
    if s in _SMS_INFLIGHT:
        return "Queued…"
    return s.capitalize() if s else "Unknown"


def is_terminal_sms_status(status) -> bool:
    """True once Twilio won't change the status further (delivered/failed)."""
    s = (status or "").strip().lower()
    return s == "delivered" or s in _SMS_FAILED
