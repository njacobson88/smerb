"""Non-crisis SI trend flag (PI-specified 2026-10-07).

Answers "have this participant's recent check-ins tended toward higher SI
risk?" — a staff-facing signal, deliberately separate from the crisis
pipeline. It never triggers outreach, paging, or anything participant-facing.

Composite per check-in: the MEAN of the SI items that were answered —
desire_intensity, intention_strength, ability_safe (risk-oriented, scale-
aware via ema_scale), thoughts_intent, and thoughts_past_4hrs as 0/100.
Mean, not max: the crisis logic uses max because one high answer must
alert; a trend wants the level of the whole picture, not its spikiest item.

Rule (approved): daily means in the participant's local timezone; flag
"rising" when the least-squares slope over the last 7 days exceeds
+2 points/day AND the last-7 mean exceeds the prior-7 mean by >= 10 points,
with at least 6 check-ins across at least 4 distinct days in the last 7.
Below that, "insufficient". A participant in their first week has no prior
week and therefore cannot flag — by design.

Pure functions first (unit tested); `compute_si_trend` does the read.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from ema_scale import ability_safe_risk_value

SI_SLIDER_FIELDS = ("desire_intensity", "intention_strength", "thoughts_intent")

SLOPE_MIN_PER_DAY = 2.0
LEVEL_DELTA_MIN = 10.0
MIN_CHECKINS_7D = 6
MIN_DAYS_7D = 4
WINDOW_DAYS = 7
SERIES_DAYS = 14

RULE = {
    "composite": "mean of answered SI items (ability_safe risk-oriented; thoughts_past_4hrs as 0/100)",
    "slopeMinPerDay": SLOPE_MIN_PER_DAY,
    "levelDeltaMin": LEVEL_DELTA_MIN,
    "minCheckins7d": MIN_CHECKINS_7D,
    "minDays7d": MIN_DAYS_7D,
    "windowDays": WINDOW_DAYS,
}


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0.0 <= f <= 100.0 else None


def _truthy(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "1"):
            return True
        if s in ("false", "no", "0"):
            return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return bool(v)
    return None


def checkin_composite(responses: Optional[Dict[str, Any]]) -> Optional[float]:
    """Mean SI composite for one check-in, or None if no SI item was answered."""
    responses = responses or {}
    vals: List[float] = []
    for f in SI_SLIDER_FIELDS:
        v = _num(responses.get(f))
        if v is not None:
            vals.append(v)
    risk = ability_safe_risk_value(responses)
    if risk is not None:
        v = _num(risk)
        if v is not None:
            vals.append(v)
    tp = _truthy(responses.get("thoughts_past_4hrs"))
    if tp is not None:
        vals.append(100.0 if tp else 0.0)
    return sum(vals) / len(vals) if vals else None


def _to_local_date(ts: Any, tz) -> Optional[date]:
    if ts is None:
        return None
    try:
        if isinstance(ts, datetime):
            dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        elif hasattr(ts, "timestamp"):
            dt = datetime.fromtimestamp(ts.timestamp(), tz=timezone.utc)
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            return None
        return dt.astimezone(tz).date()
    except Exception:
        return None


def daily_means(checkins: Iterable[Dict[str, Any]], tz) -> Dict[date, Dict[str, float]]:
    """{local date: {"mean": composite mean, "n": check-ins with a composite}}."""
    acc: Dict[date, List[float]] = {}
    for c in checkins or []:
        comp = checkin_composite(c.get("responses"))
        if comp is None:
            continue
        d = _to_local_date(c.get("completedAt"), tz)
        if d is None:
            continue
        acc.setdefault(d, []).append(comp)
    return {d: {"mean": sum(v) / len(v), "n": len(v)} for d, v in acc.items()}


def _ols_slope(points: List[tuple]) -> Optional[float]:
    """Least-squares slope of (x, y) points; None with fewer than 2 points."""
    if len(points) < 2:
        return None
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    if sxx == 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in points) / sxx


def trend_summary(daily: Dict[date, Dict[str, float]], today: date) -> Dict[str, Any]:
    """Apply the approved rule to per-day composites. Pure."""
    last_start = today - timedelta(days=WINDOW_DAYS - 1)
    prior_start = last_start - timedelta(days=WINDOW_DAYS)
    prior_end = last_start - timedelta(days=1)

    last = {d: v for d, v in daily.items() if last_start <= d <= today}
    prior = {d: v for d, v in daily.items() if prior_start <= d <= prior_end}

    checkins7 = sum(int(v["n"]) for v in last.values())
    days7 = len(last)

    def _mean(block: Dict[date, Dict[str, float]]) -> Optional[float]:
        # Weight days by their check-in count so a single stray answer does
        # not count as much as a full day of three.
        tot_n = sum(int(v["n"]) for v in block.values())
        if tot_n == 0:
            return None
        return sum(v["mean"] * v["n"] for v in block.values()) / tot_n

    last_mean = _mean(last)
    prior_mean = _mean(prior)
    slope = _ols_slope([((d - last_start).days, v["mean"]) for d, v in sorted(last.items())])
    level_delta = (last_mean - prior_mean) if (last_mean is not None and prior_mean is not None) else None

    if checkins7 < MIN_CHECKINS_7D or days7 < MIN_DAYS_7D:
        status = "insufficient"
    elif (slope is not None and slope > SLOPE_MIN_PER_DAY
          and level_delta is not None and level_delta >= LEVEL_DELTA_MIN):
        status = "rising"
    else:
        status = "stable"

    series_start = today - timedelta(days=SERIES_DAYS - 1)
    series = []
    for i in range(SERIES_DAYS):
        d = series_start + timedelta(days=i)
        v = daily.get(d)
        series.append({"date": d.isoformat(),
                       "mean": round(v["mean"], 1) if v else None,
                       "n": int(v["n"]) if v else 0})

    return {
        "status": status,
        "slopePerDay": round(slope, 2) if slope is not None else None,
        "last7Mean": round(last_mean, 1) if last_mean is not None else None,
        "prior7Mean": round(prior_mean, 1) if prior_mean is not None else None,
        "levelDelta": round(level_delta, 1) if level_delta is not None else None,
        "checkins7": checkins7,
        "days7": days7,
        "noPriorWeek": prior_mean is None,
        "series": series,
        "rule": RULE,
    }


def compact(summary: Dict[str, Any]) -> Dict[str, Any]:
    """The few fields the overview table needs per participant."""
    return {k: summary.get(k) for k in ("status", "slopePerDay", "levelDelta", "last7Mean", "checkins7", "days7")}


def compute_si_trend(participant_id: str, db, config, tz_name: Optional[str] = None,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """Read the last 14+ days of check-ins and summarize. Never raises."""
    from zoneinfo import ZoneInfo
    from participant_schedule import load_schedule, DEFAULT_TZ

    try:
        if not tz_name:
            tz_name = load_schedule(participant_id, db, config).get("tz") or DEFAULT_TZ
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz_name, tz = DEFAULT_TZ, ZoneInfo(DEFAULT_TZ)

        now_utc = now or datetime.now(timezone.utc)
        today_local = now_utc.astimezone(tz).date()
        # One extra day of slack so a late-evening local date is never cut off.
        since = now_utc - timedelta(days=SERIES_DAYS + 1)

        rows = []
        try:
            q = (db.collection(config.col("participants")).document(participant_id)
                   .collection("ema_responses").where("completedAt", ">=", since))
            rows = [x.to_dict() or {} for x in q.stream()]
        except Exception:
            rows = []

        summary = trend_summary(daily_means(rows, tz), today_local)
        summary.update({"participantId": participant_id, "tz": tz_name,
                        "computedAt": now_utc.isoformat()})
        return summary
    except Exception as e:  # a trend must never break a page
        return {"participantId": participant_id, "status": "insufficient", "error": str(e),
                "series": [], "rule": RULE}
