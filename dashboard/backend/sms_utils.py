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
