"""Per-day aggregation for the participant summary — pure, unit-tested.

The participant page used to stream every event document the participant
ever produced (57k for the heaviest user, OCR transcripts included) on every
view: 5–70 s per page (2026-10-30). The day totals for any date before today
never change except for late-syncing devices, so they are now kept in a
per-participant cache document that the hourly refresh updates incrementally;
the page computes only the last two days live and overlays them.

This module holds the aggregation and merge rules; main.py owns Firestore I/O.
Date keys are YYYY-MM-DD in the server's zone (UTC on Cloud Run), exactly as
the endpoint always computed them.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional
import json

# Recompute this many days before the cache's last complete day on each
# incremental refresh, so EMAs/events that sync late (we have seen 14 h lags)
# still land in the right day.
INCREMENTAL_LOOKBACK_DAYS = 2
# Rebuild from scratch at least this often, catching anything later than that.
FULL_REBUILD_EVERY_HOURS = 24
# The page always recomputes these most recent days live.
LIVE_TAIL_DAYS = 2


def empty_day() -> Dict[str, Any]:
    return {"screenshots": 0, "ocr_words": 0, "ocr_chars": 0,
            "reddit": 0, "twitter": 0, "checkins": 0, "safety_alerts": 0,
            "crisis_indicated": False}


def day_key(value) -> Optional[str]:
    """YYYY-MM-DD for a Firestore timestamp / datetime / ISO string, matching the
    endpoint's historical behaviour (server-local via fromtimestamp)."""
    if not value:
        return None
    if hasattr(value, "timestamp") and not isinstance(value, datetime):
        return datetime.fromtimestamp(value.timestamp()).strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        return datetime.fromtimestamp(value.timestamp()).strftime("%Y-%m-%d") if value.tzinfo else value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        return value[:10]
    return None


def aggregate(events: Iterable[dict], checkins: Iterable[dict], alerts: Iterable[dict]) -> Dict[str, Dict[str, Any]]:
    """Fold event / check-in / alert dicts into {date: totals}."""
    days: Dict[str, Dict[str, Any]] = defaultdict(empty_day)
    for ev in events:
        d = day_key(ev.get("timestamp") or ev.get("createdAt"))
        if not d:
            continue
        if ev.get("eventType", ev.get("type", "")) == "screenshot":
            row = days[d]
            row["screenshots"] += 1
            platform = ev.get("platform", "unknown")
            if platform in ("reddit", "twitter"):
                row[platform] += 1
            ocr = ev.get("ocr") or {}
            wc = ocr.get("wordCount", 0) if isinstance(ocr, dict) else 0
            if wc:
                row["ocr_words"] += wc
                row["ocr_chars"] += wc * 5
    for ci in checkins:
        d = day_key(ci.get("completedAt"))
        if not d:
            continue
        row = days[d]
        row["checkins"] += 1
        responses = ci.get("responses", {})
        if isinstance(responses, str):
            try:
                responses = json.loads(responses)
            except (json.JSONDecodeError, TypeError, ValueError):
                responses = {}
        for key, value in (responses or {}).items():
            if isinstance(value, str) and value.lower() in ("yes", "true"):
                lk = key.lower()
                if "crisis" in lk or "harm" in lk or "hurt" in lk:
                    row["crisis_indicated"] = True
    for al in alerts:
        d = day_key(al.get("triggeredAt"))
        if d:
            days[d]["safety_alerts"] += 1
    return dict(days)


def merge_days(cached: Dict[str, Dict[str, Any]], fresh: Dict[str, Dict[str, Any]],
               fresh_from: str) -> Dict[str, Dict[str, Any]]:
    """Cached days before `fresh_from` + freshly computed days from it on.

    Every cached day >= fresh_from is dropped first: if it has no events any
    more (data was re-dated, or the day genuinely had none) it must not survive
    from the stale copy.
    """
    out = {d: v for d, v in (cached or {}).items() if d < fresh_from}
    for d, v in (fresh or {}).items():
        if d >= fresh_from:
            out[d] = v
    return out


def incremental_window(cached_through: Optional[str], full_rebuilt_at: Optional[datetime],
                       now: datetime) -> Optional[str]:
    """Which date to recompute from on this refresh — None means full rebuild."""
    if not cached_through or full_rebuilt_at is None:
        return None
    if now - full_rebuilt_at >= timedelta(hours=FULL_REBUILD_EVERY_HOURS):
        return None
    through = datetime.strptime(cached_through, "%Y-%m-%d")
    return (through - timedelta(days=INCREMENTAL_LOOKBACK_DAYS - 1)).strftime("%Y-%m-%d")


def history_cutoff(now: datetime) -> str:
    """Last date the cache is responsible for; later days are computed live."""
    return (now - timedelta(days=LIVE_TAIL_DAYS)).strftime("%Y-%m-%d")
