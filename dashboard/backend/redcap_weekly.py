"""REDCap weekly-survey completion + automated-reminder status.

Two things study staff need that live in REDCap rather than Firestore:

1. **Weekly survey completion.** `weekly_survey_arm_1` is a repeating event; each
   repeat instance is one week's battery of 11 instruments. REDCap stamps a
   `<instrument>_timestamp` per survey and a `<instrument>_complete` status
   (0 = incomplete, 1 = unverified, 2 = complete). There is no single
   "weekly survey done" field, so completion is derived from those.
2. **Reminders.** The `reminders` instrument (event `reminders_arm_1`) is the
   switchboard Justine set up to gate REDCap's automated survey invitations —
   one radio per contact type, `1 = Send` / `0 = Cancel`.

Everything here is pure except `fetch_*`, so the derivations are unit-testable
without touching the live project.
"""

import html
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests as http_requests

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weekly survey
# ---------------------------------------------------------------------------

WEEKLY_SURVEY_EVENT = "weekly_survey_arm_1"

# Order matters: this is the order REDCap serves them, so `wkly_resources`
# (the resource page shown after the last measure) is the completion sentinel.
WEEKLY_SURVEY_INSTRUMENTS = (
    "phq_9",
    "gad_7",
    "social_media_use_measure",
    "cssrs_weekly",
    "bas_2",
    "weight_questionnaire",
    "weekly_alcohol_and_drug_followback",
    "ucla_loneliness_scale10",
    "life_events",
    "swls",
    "wkly_resources",
)
WEEKLY_SURVEY_FINAL_INSTRUMENT = WEEKLY_SURVEY_INSTRUMENTS[-1]

REDCAP_STATUS_COMPLETE = "2"

# REDCap stamps survey timestamps in the server's local time, not UTC.
REDCAP_TIMEZONE = "America/New_York"

_REDCAP_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def _utc_offset(naive_local: datetime) -> timedelta:
    """Offset to add to a REDCap-local timestamp to get UTC."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(REDCAP_TIMEZONE)
        return -naive_local.replace(tzinfo=tz).utcoffset()
    except Exception:
        # No tzdata available: fall back to Eastern Standard Time. Worst case
        # this is an hour off, which never changes a 7-day window verdict.
        return timedelta(hours=5)


def parse_redcap_timestamp(value: Any) -> Optional[datetime]:
    """Parse a REDCap survey timestamp into a naive UTC datetime.

    REDCap writes the literal string `[not completed]` into `<form>_timestamp`
    when a survey was opened but never submitted, so the field being non-empty
    is NOT evidence of completion.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.startswith("["):
        return None
    for fmt in _REDCAP_TS_FORMATS:
        try:
            local = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return local + _utc_offset(local)
    return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


def summarize_weekly_survey_instance(row: Dict[str, Any]) -> Dict[str, Any]:
    """Derive completion for a single repeat instance of the weekly battery."""
    per_instrument = []
    completed = 0
    timestamps = []
    for instrument in WEEKLY_SURVEY_INSTRUMENTS:
        status = str(row.get(f"{instrument}_complete") or "").strip()
        ts = parse_redcap_timestamp(row.get(f"{instrument}_timestamp"))
        is_complete = status == REDCAP_STATUS_COMPLETE
        if is_complete:
            completed += 1
        if ts:
            timestamps.append(ts)
        per_instrument.append({
            "instrument": instrument,
            "complete": is_complete,
            "status": status or "0",
            "completedAt": _iso(ts),
        })

    final_complete = str(
        row.get(f"{WEEKLY_SURVEY_FINAL_INSTRUMENT}_complete") or ""
    ).strip() == REDCAP_STATUS_COMPLETE
    is_complete = final_complete or completed == len(WEEKLY_SURVEY_INSTRUMENTS)

    last_activity = max(timestamps) if timestamps else None
    finished_at = (
        parse_redcap_timestamp(row.get(f"{WEEKLY_SURVEY_FINAL_INSTRUMENT}_timestamp"))
        or last_activity
    ) if is_complete else None

    try:
        instance = int(row.get("redcap_repeat_instance") or 1)
    except (TypeError, ValueError):
        instance = 1

    return {
        "instance": instance,
        "status": "completed" if is_complete else ("partial" if completed or last_activity else "none"),
        "complete": is_complete,
        "instrumentsCompleted": completed,
        "instrumentsTotal": len(WEEKLY_SURVEY_INSTRUMENTS),
        "completedAt": _iso(finished_at),
        "lastActivityAt": _iso(last_activity),
        "instruments": per_instrument,
        "_completed_at": finished_at,
        "_last_activity": last_activity,
    }


def summarize_weekly_survey(
    rows: List[Dict[str, Any]],
    now: Optional[datetime] = None,
    window_days: int = 7,
) -> Dict[str, Any]:
    """Summarize weekly-survey completion, focused on the past `window_days`.

    `rows` are REDCap flat records for ONE participant, exported with
    `exportSurveyFields=true`. Rows for other events are ignored.
    """
    now = now or datetime.utcnow()
    window_start = now - timedelta(days=window_days)

    instances = []
    for row in rows or []:
        if row.get("redcap_event_name") and row["redcap_event_name"] != WEEKLY_SURVEY_EVENT:
            continue
        summary = summarize_weekly_survey_instance(row)
        if summary["status"] == "none":
            continue
        instances.append(summary)

    instances.sort(
        key=lambda s: (s["_last_activity"] or datetime.min, s["instance"]),
        reverse=True,
    )

    in_window = [
        s for s in instances
        if (s["_last_activity"] or datetime.min) >= window_start
    ]
    completed_in_window = [s for s in in_window if s["complete"]]
    all_completed = [s for s in instances if s["complete"]]

    if completed_in_window:
        status = "completed"
        focus = completed_in_window[0]
    elif in_window:
        status = "partial"
        focus = in_window[0]
    else:
        status = "none"
        focus = instances[0] if instances else None

    last_completed = all_completed[0] if all_completed else None

    result = {
        "status": status,
        "completedInWindow": bool(completed_in_window),
        "startedInWindow": bool(in_window),
        "windowDays": window_days,
        "windowStart": _iso(window_start),
        "lastCompletedAt": last_completed["completedAt"] if last_completed else None,
        "lastCompletedInstance": last_completed["instance"] if last_completed else None,
        "lastActivityAt": focus["lastActivityAt"] if focus else None,
        "instrumentsCompleted": focus["instrumentsCompleted"] if focus else 0,
        "instrumentsTotal": len(WEEKLY_SURVEY_INSTRUMENTS),
        "currentInstance": focus["instance"] if focus else None,
        "totalCompleted": len(all_completed),
        "instances": [
            {k: v for k, v in s.items() if not k.startswith("_")}
            for s in instances
        ],
    }
    result.update(weekly_survey_email_variables(result, focus))
    return result


def _friendly_date(iso_value: Optional[str]) -> Optional[str]:
    if not iso_value:
        return None
    try:
        return datetime.strptime(iso_value[:10], "%Y-%m-%d").strftime("%b %-d")
    except ValueError:
        try:
            return datetime.strptime(iso_value[:10], "%Y-%m-%d").strftime("%b %d")
        except ValueError:
            return None


def weekly_survey_email_variables(
    summary: Dict[str, Any], focus: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """Render the weekly-survey status into the variables the email templates use."""
    status = summary.get("status")
    done = summary.get("instrumentsCompleted") or 0
    total = summary.get("instrumentsTotal") or len(WEEKLY_SURVEY_INSTRUMENTS)

    if status == "completed":
        when = _friendly_date(
            (focus or {}).get("completedAt") or summary.get("lastCompletedAt")
        )
        label = "Completed"
        detail = f"completed{f' on {when}' if when else ''}"
        line = f"📝 Weekly Survey: ✅ Completed{f' {when}' if when else ''}"
    elif status == "partial":
        label = "Started, not finished"
        detail = f"started ({done} of {total} sections done)"
        line = (
            f"📝 Weekly Survey: ⏳ Started but not finished "
            f"({done} of {total} sections) — it only takes a few minutes to wrap up"
        )
    else:
        label = "Not completed"
        detail = "not completed in the past week"
        line = "📝 Weekly Survey: ⬜ Not completed this week — we'd love to have it when you get a chance"

    return {
        "weekly_survey_status": label,
        "weekly_survey_detail": detail,
        "weekly_survey_line": line,
    }


# The subset of the summary that compliance email templates substitute.
WEEKLY_SURVEY_TEMPLATE_KEYS = (
    "weekly_survey_status",
    "weekly_survey_detail",
    "weekly_survey_line",
)

# Used when REDCap is unreachable — the email must still render.
WEEKLY_SURVEY_UNAVAILABLE = {
    "weekly_survey_status": "Unknown",
    "weekly_survey_detail": "status unavailable",
    "weekly_survey_line": "📝 Weekly Survey: status unavailable",
}


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

REMINDERS_EVENT = "reminders_arm_1"
REMINDERS_FORM = "reminders"

# Fallback labels, used when the REDCap data dictionary can't be reached. Kept in
# the order Justine laid the instrument out.
REMINDER_FIELD_LABELS = {
    "reminder_wkly": "Weekly survey reminder",
    "reminder_baseline": "Baseline survey reminder",
    "reminder_exit": "Exit survey reminder",
    "interview_late": "Participation interview: LATE",
    "interview_no_show": "Participation interview: NO SHOW",
    "ic_drop": "Drop off at informed consent",
    "interview_reminder": "Participation interview: MANUAL REMINDER",
    "post_interv_not_eligible": "Post interview follow-up: NOT ELIGIBLE",
    "post_interv_eligible": "Post interview follow-up: ELIGIBLE TO ENROLL",
    "participant_welcome_manual": "Participant welcome email (manual)",
    "eligible_interview_manual": "ELIGIBLE (manual)",
    "not_eligible_interv_manual": "NOT ELIGIBLE (manual)",
}
REMINDER_FIELDS = tuple(REMINDER_FIELD_LABELS)

REMINDER_CHOICE_LABELS = {"1": "Send", "0": "Cancel"}

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(value: str) -> str:
    """REDCap rich-text labels arrive as HTML; notes should show plain text."""
    if not value:
        return ""
    text = _TAG_RE.sub(" ", value)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_choices(raw: str) -> Dict[str, str]:
    """Parse a REDCap `select_choices_or_calculations` string into {code: label}."""
    choices = {}
    for part in (raw or "").split("|"):
        code, sep, label = part.partition(",")
        if not sep:
            continue
        code = code.strip()
        label = strip_html(label).rstrip(",").strip()
        if code:
            choices[code] = label or code
    return choices


def summarize_reminders(
    row: Optional[Dict[str, Any]],
    labels: Optional[Dict[str, str]] = None,
    choices: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Turn the `reminders` instrument row into a display-ready list.

    Returns every reminder switch, set or not, so staff can see at a glance which
    automated contacts are armed for this participant.
    """
    row = row or {}
    labels = labels or {}
    choices = choices or {}

    items = []
    set_count = 0
    for field in REMINDER_FIELDS:
        raw = str(row.get(field) or "").strip()
        field_choices = choices.get(field) or REMINDER_CHOICE_LABELS
        value_label = field_choices.get(raw) if raw else None
        if raw:
            set_count += 1
        items.append({
            "field": field,
            "label": labels.get(field) or REMINDER_FIELD_LABELS[field],
            "value": raw or None,
            "valueLabel": value_label or ("Not set" if not raw else raw),
            "send": raw == "1",
            "cancelled": raw == "0",
        })

    status = str(row.get(f"{REMINDERS_FORM}_complete") or "").strip()
    return {
        "hasData": set_count > 0,
        "setCount": set_count,
        "total": len(REMINDER_FIELDS),
        "formStatus": status or None,
        "updatedAt": _iso(parse_redcap_timestamp(row.get(f"{REMINDERS_FORM}_timestamp"))),
        "reminders": items,
    }


# ---------------------------------------------------------------------------
# REDCap fetches
# ---------------------------------------------------------------------------

def _redcap_post(payload: Dict[str, Any], timeout: int = 30) -> Any:
    if not config.REDCAP_API_URL or not config.REDCAP_API_TOKEN:
        raise RuntimeError("REDCap API not configured")
    resp = http_requests.post(
        config.REDCAP_API_URL,
        data={"token": config.REDCAP_API_TOKEN, "format": "json",
              "returnFormat": "json", **payload},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"REDCap API error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def fetch_weekly_survey_rows(record_id: str) -> List[Dict[str, Any]]:
    """Export every weekly-survey repeat instance for one record."""
    rows = _redcap_post({
        "content": "record",
        "type": "flat",
        "records[0]": record_id,
        "events[0]": WEEKLY_SURVEY_EVENT,
        "exportSurveyFields": "true",
    }, timeout=60)
    return [r for r in rows if isinstance(r, dict)]


_reminder_meta_cache: Dict[str, Any] = {"at": 0.0, "labels": {}, "choices": {}}
_REMINDER_META_TTL = 3600


def fetch_reminder_metadata() -> Dict[str, Any]:
    """Labels/choices for the reminders instrument, cached for an hour.

    Read from REDCap rather than hardcoded so renaming a reminder in REDCap shows
    up in the dashboard; falls back to the static map on any failure.
    """
    now = time.time()
    if _reminder_meta_cache["labels"] and now - _reminder_meta_cache["at"] < _REMINDER_META_TTL:
        return _reminder_meta_cache

    try:
        meta = _redcap_post({"content": "metadata", "forms[0]": REMINDERS_FORM})
        labels, choices = {}, {}
        for field in meta:
            name = field.get("field_name")
            if not name:
                continue
            labels[name] = strip_html(field.get("field_label") or "") or name
            parsed = parse_choices(field.get("select_choices_or_calculations") or "")
            if parsed:
                choices[name] = parsed
        if labels:
            _reminder_meta_cache.update({"at": now, "labels": labels, "choices": choices})
    except Exception as e:
        logger.warning(f"[REDCap] reminder metadata fetch failed, using static labels: {e}")

    return _reminder_meta_cache


def fetch_reminders(record_id: str) -> Dict[str, Any]:
    """Fetch and summarize the reminders switchboard for one record."""
    # Export by form (not field list) so REDCap also returns `reminders_complete`
    # and `reminders_timestamp`, which it only emits for whole-form exports.
    rows = _redcap_post({
        "content": "record",
        "type": "flat",
        "records[0]": record_id,
        "events[0]": REMINDERS_EVENT,
        "forms[0]": REMINDERS_FORM,
        "exportSurveyFields": "true",
    })

    row = next((r for r in rows if isinstance(r, dict)), None)
    meta = fetch_reminder_metadata()
    return summarize_reminders(row, meta.get("labels"), meta.get("choices"))
