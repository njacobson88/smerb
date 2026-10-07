"""A participant's EMA prompt schedule and local timezone, reconstructed from
what the device logged.

The wake-up time that drives the three daily windows lives only in the app's
SharedPreferences — it is never written to Firestore. But every time the app
(re)schedules its reminders it logs an `ema_notification_scheduled` row per
window carrying `timeOfDay` ("11:00"), `firstFireAt` and `tz`. Grouped by the
day they were scheduled, those rows ARE the schedule, including changes over
time. Devices that never logged (the Android 1.0.18 cohort, see
project_safety_pipeline_incident_2026-10) fall back to the study default.

`infer_schedule` is pure and unit tested; `load_schedule` does the read.
"""

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_PROMPT_TIMES = ("11:00", "15:00", "19:00")
DEFAULT_TZ = "America/New_York"
WINDOWS_PER_DAY = 3


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "timestamp"):
        try:
            return datetime.utcfromtimestamp(value.timestamp()).date()
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d").date()
            except ValueError:
                return None
    return None


def _valid_time(t: Any) -> Optional[str]:
    if not isinstance(t, str) or len(t) != 5 or t[2] != ":":
        return None
    try:
        h, m = int(t[:2]), int(t[3:])
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return t


def infer_schedule(log_rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a schedule timeline from `ema_notification_scheduled` log rows.

    Returns {"timeline": [{"from": date, "promptTimes": [..]}, ...] sorted
    ascending, "tz": str, "source": "logged"|"default", "current": [..]}.
    A timeline entry is created for each day on which a full set of windows
    was scheduled; `prompt_times_on(schedule, d)` picks the one in effect.
    """
    by_day: Dict[date, set] = {}
    tz: Optional[str] = None
    for row in log_rows or []:
        if row.get("eventType") != "ema_notification_scheduled":
            continue
        data = row.get("data") or {}
        t = _valid_time(data.get("timeOfDay"))
        if not t:
            continue
        # Prefer the day the first fire was scheduled for; fall back to when logged.
        d = _parse_date(data.get("firstFireAt")) or _parse_date(row.get("timestamp")) or _parse_date(row.get("localTime"))
        if d is None:
            continue
        by_day.setdefault(d, set()).add(t)
        if not tz and isinstance(data.get("tz"), str) and "/" in data["tz"]:
            tz = data["tz"]

    timeline: List[Dict[str, Any]] = []
    last: Optional[tuple] = None
    for d in sorted(by_day):
        times = tuple(sorted(by_day[d]))
        if len(times) < WINDOWS_PER_DAY:
            continue  # partial reschedule (e.g. one window re-armed) — not a new schedule
        times = times[:WINDOWS_PER_DAY]
        if times != last:
            timeline.append({"from": d, "promptTimes": list(times)})
            last = times

    if not timeline:
        return {"timeline": [], "tz": tz or DEFAULT_TZ, "source": "default",
                "current": list(DEFAULT_PROMPT_TIMES)}
    return {"timeline": timeline, "tz": tz or DEFAULT_TZ, "source": "logged",
            "current": timeline[-1]["promptTimes"]}


def prompt_times_on(schedule: Dict[str, Any], d: date) -> List[str]:
    """Prompt times in effect on local date `d`.

    Before the first logged schedule we still use that first schedule rather
    than the default: a participant whose device logged 12/16/20 on day 3 was
    almost certainly on 12/16/20 on days 1-2 too (the log only starts when
    the fixed app version is installed).
    """
    timeline = schedule.get("timeline") or []
    if not timeline:
        return list(DEFAULT_PROMPT_TIMES)
    chosen = timeline[0]["promptTimes"]
    for entry in timeline:
        if entry["from"] <= d:
            chosen = entry["promptTimes"]
        else:
            break
    return list(chosen)


def load_schedule(participant_id: str, db, config, limit: int = 600) -> Dict[str, Any]:
    """Read the device's scheduling log and infer the schedule. Never raises."""
    rows: List[Dict[str, Any]] = []
    try:
        q = (db.collection(config.col("participants")).document(participant_id)
               .collection("notification_log")
               .where("eventType", "==", "ema_notification_scheduled")
               .limit(limit))
        rows = [x.to_dict() or {} for x in q.stream()]
    except Exception:
        rows = []
    return infer_schedule(rows)
