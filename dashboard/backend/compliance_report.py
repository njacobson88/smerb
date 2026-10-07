"""Study-wide compliance and compensation report (PI-specified 2026-10-07).

Read-only. Nothing in this module writes to any participant record.

Compensation schedule (PI):
  $10   screening complete in REDCap          (cssrs_screener, consent__screener_arm_1)
  $20   baseline interview complete in REDCap (interview_questions, interview_arm_1)
  $1    per EMA completed within 4 h of its prompt, one per window, cap $270
  $1.50 per study week with "regular" app use: >= 3 active days AND >= 150 screenshots
  $20   exit survey complete in REDCap        (exit_resources, exit_arm_1)
  $0    weekly REDCap surveys and the post-interview baseline battery (tracked, unpaid)

Prompt times come from the device's own scheduling log (participant_schedule);
devices that never logged use the study default. A check-in is credited to the
most recent prompt it follows within 4 hours; off-window completions are shown
but not paid. The 90-day period is 12 full weeks plus a 6-day final period held
to the same threshold.

Pure functions first (unit tested); `build_compliance_report` does the reads.
"""

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from participant_schedule import prompt_times_on

PAY_SCREENING = 10.00
PAY_INTERVIEW = 20.00
PAY_EXIT = 20.00
PAY_PER_EMA = 1.00
EMA_CAP = 270
PAY_PER_APP_WEEK = 1.50
APP_WEEK_MIN_ACTIVE_DAYS = 3
APP_WEEK_MIN_SCREENSHOTS = 150
STUDY_DAYS = 90
EMA_CREDIT_HOURS = 4
WEEK_PERIODS = 13  # 12 x 7 days + 1 x 6 days

RULES = {
    "screening": PAY_SCREENING, "interview": PAY_INTERVIEW, "exit": PAY_EXIT,
    "perEma": PAY_PER_EMA, "emaCap": EMA_CAP, "emaCreditHours": EMA_CREDIT_HOURS,
    "perAppWeek": PAY_PER_APP_WEEK, "appWeekMinActiveDays": APP_WEEK_MIN_ACTIVE_DAYS,
    "appWeekMinScreenshots": APP_WEEK_MIN_SCREENSHOTS, "studyDays": STUDY_DAYS,
    "weekPeriods": WEEK_PERIODS, "weeklySurveyPay": 0.0, "baselineBatteryPay": 0.0,
}

MAX_POSSIBLE = PAY_SCREENING + PAY_INTERVIEW + EMA_CAP * PAY_PER_EMA + WEEK_PERIODS * PAY_PER_APP_WEEK + PAY_EXIT

# REDCap instruments that carry each paid completion, and the baseline battery.
REDCAP_SCREENING = ("consent__screener_arm_1", "cssrs_screener")
REDCAP_INTERVIEW = ("interview_arm_1", "interview_questions")
REDCAP_EXIT = ("exit_arm_1", "exit_resources")
REDCAP_BASELINE_EVENT = "postinterview_base_arm_1"
REDCAP_BASELINE_FORMS = (
    "idas_2", "phq_9", "gad_7", "social_media_use_measure", "ace_adults", "ders",
    "scale_of_protective_factors", "brs", "bas_2", "weight_questionnaire",
    "weekly_alcohol_and_drug_followback", "ucla_loneliness_scale10", "life_events",
    "swls", "dsm5_l1_crosscutting_nda", "whodas_2_nda", "baseline_resources",
)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _to_utc(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    try:
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        if hasattr(ts, "timestamp"):
            return datetime.fromtimestamp(ts.timestamp(), tz=timezone.utc)
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return None


def _hm(t: str) -> time:
    return time(int(t[:2]), int(t[3:]))


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------------------
# EMA crediting
# ---------------------------------------------------------------------------

def credit_emas(checkins: Iterable[Dict[str, Any]], schedule: Dict[str, Any], tz,
                study_start: date, today: date) -> Dict[str, Any]:
    """Credit each check-in to the prompt it followed within EMA_CREDIT_HOURS.

    One credit per (local date, prompt time). The participant can complete a
    check-in at any time; those that follow no prompt within the window, or
    duplicate an already-credited window, are counted as `offWindow`.
    """
    study_end = study_start + timedelta(days=STUDY_DAYS - 1)
    last_day = min(today, study_end)

    credited: Dict[tuple, datetime] = {}
    off_window: List[Dict[str, Any]] = []
    completed_total = 0

    for c in checkins or []:
        dt_utc = _to_utc(c.get("completedAt"))
        if dt_utc is None:
            continue
        local = dt_utc.astimezone(tz)
        ld = local.date()
        if ld < study_start or ld > study_end:
            continue
        completed_total += 1

        # Candidate prompts: today's and yesterday's (a late window can cross midnight).
        best = None
        for cand_day in (ld, ld - timedelta(days=1)):
            for t in prompt_times_on(schedule, cand_day):
                p = datetime.combine(cand_day, _hm(t), tzinfo=tz)
                if p <= local < p + timedelta(hours=EMA_CREDIT_HOURS):
                    if best is None or p > best[0]:
                        best = (p, cand_day, t)
        if best is None:
            off_window.append({"completedAt": _iso(dt_utc), "reason": "no_prompt_within_window"})
            continue
        key = (best[1], best[2])
        if key in credited:
            off_window.append({"completedAt": _iso(dt_utc), "reason": "window_already_credited",
                               "window": f"{best[1].isoformat()} {best[2]}"})
            continue
        credited[key] = dt_utc

    # Day-by-day view over the elapsed study period.
    days: List[Dict[str, Any]] = []
    expected = 0
    d = study_start
    while d <= last_day:
        prompts = []
        for t in prompt_times_on(schedule, d):
            # Only prompts that have already fired count as expected.
            fired = datetime.combine(d, _hm(t), tzinfo=tz) <= datetime.now(tz)
            hit = credited.get((d, t))
            if fired:
                expected += 1
            prompts.append({"time": t, "fired": fired, "credited": hit is not None,
                            "completedAt": _iso(hit)})
        days.append({"date": d.isoformat(),
                     "credited": sum(1 for p in prompts if p["credited"]),
                     "expected": sum(1 for p in prompts if p["fired"]),
                     "prompts": prompts})
        d += timedelta(days=1)

    n_credited = len(credited)
    return {
        "credited": n_credited,
        "creditedPaid": min(n_credited, EMA_CAP),
        "completed": completed_total,
        "offWindow": len(off_window),
        "offWindowDetail": off_window[:50],
        "expectedToDate": expected,
        "rate": round(n_credited / expected, 3) if expected else None,
        "days": days,
    }


# ---------------------------------------------------------------------------
# Weekly app use
# ---------------------------------------------------------------------------

def week_periods(study_start: date) -> List[Dict[str, Any]]:
    """12 full weeks + a 6-day final period covering days 1..90."""
    out = []
    for i in range(WEEK_PERIODS):
        s = study_start + timedelta(days=7 * i)
        e = min(s + timedelta(days=6), study_start + timedelta(days=STUDY_DAYS - 1))
        out.append({"week": i + 1, "start": s, "end": e, "days": (e - s).days + 1})
    return out


def weekly_app_use(daily_screenshots: Dict[date, Dict[str, int]], study_start: date,
                   today: date) -> Dict[str, Any]:
    """Qualify each period: >= 3 active days AND >= 150 screenshots (Reddit + X)."""
    weeks = []
    for p in week_periods(study_start):
        shots = reddit = twitter = 0
        active = 0
        d = p["start"]
        while d <= p["end"]:
            v = daily_screenshots.get(d) or {}
            n = int(v.get("total", 0))
            shots += n
            reddit += int(v.get("reddit", 0))
            twitter += int(v.get("twitter", 0))
            if n > 0:
                active += 1
            d += timedelta(days=1)
        complete = p["end"] <= today
        started = p["start"] <= today
        qualifies = active >= APP_WEEK_MIN_ACTIVE_DAYS and shots >= APP_WEEK_MIN_SCREENSHOTS
        weeks.append({
            "week": p["week"], "start": p["start"].isoformat(), "end": p["end"].isoformat(),
            "days": p["days"], "activeDays": active, "screenshots": shots,
            "reddit": reddit, "twitter": twitter,
            "started": started, "complete": complete, "qualifies": qualifies,
            "paid": qualifies and complete,
            "onTrack": qualifies and started and not complete,
        })
    return {
        "weeks": weeks,
        "paidWeeks": sum(1 for w in weeks if w["paid"]),
        "completedWeeks": sum(1 for w in weeks if w["complete"]),
        "qualifyingWeeks": sum(1 for w in weeks if w["qualifies"]),
    }


# ---------------------------------------------------------------------------
# REDCap completions
# ---------------------------------------------------------------------------

def parse_redcap_completions(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """From a flat export (exportSurveyFields=true) of the three paid events +
    the baseline battery, decide what is complete and when."""
    from redcap_weekly import parse_redcap_timestamp
    by_event: Dict[str, Dict[str, Any]] = {}
    for r in rows or []:
        ev = r.get("redcap_event_name")
        if ev and ev not in by_event:
            by_event[ev] = r

    def _done(ev: str, form: str) -> Dict[str, Any]:
        r = by_event.get(ev) or {}
        complete = str(r.get(f"{form}_complete") or "").strip() == "2"
        ts = parse_redcap_timestamp(r.get(f"{form}_timestamp"))
        return {"complete": complete, "at": ts.isoformat() + "Z" if ts else None,
                "instrument": form, "event": ev}

    base = by_event.get(REDCAP_BASELINE_EVENT) or {}
    done_forms = [f for f in REDCAP_BASELINE_FORMS if str(base.get(f"{f}_complete") or "").strip() == "2"]
    return {
        "screening": _done(*REDCAP_SCREENING),
        "interview": _done(*REDCAP_INTERVIEW),
        "exit": _done(*REDCAP_EXIT),
        "baselineBattery": {"completed": len(done_forms), "total": len(REDCAP_BASELINE_FORMS),
                            "complete": len(done_forms) == len(REDCAP_BASELINE_FORMS),
                            "missing": [f for f in REDCAP_BASELINE_FORMS if f not in done_forms]},
    }


def fetch_redcap_completions(record_id: str) -> Dict[str, Any]:
    """One export covering the paid events + baseline battery, plus the weekly summary."""
    from redcap_weekly import _redcap_post, fetch_weekly_survey_rows, summarize_weekly_survey
    rows = _redcap_post({
        "content": "record", "type": "flat", "records[0]": record_id,
        "events[0]": REDCAP_SCREENING[0], "events[1]": REDCAP_INTERVIEW[0],
        "events[2]": REDCAP_EXIT[0], "events[3]": REDCAP_BASELINE_EVENT,
        "exportSurveyFields": "true",
    }, timeout=60)
    out = parse_redcap_completions([r for r in rows if isinstance(r, dict)])
    weekly = summarize_weekly_survey(fetch_weekly_survey_rows(record_id), window_days=7)
    out["weekly"] = {k: weekly.get(k) for k in ("totalCompleted", "lastCompletedAt", "status", "instances")}
    out["available"] = True
    out["recordId"] = record_id
    return out


# ---------------------------------------------------------------------------
# Compensation
# ---------------------------------------------------------------------------

def compensation(ema: Dict[str, Any], app: Dict[str, Any], redcap: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rc = redcap or {}
    def flag(key):
        return bool(((rc.get(key) or {}).get("complete")))
    lines = [
        {"item": "Screening (REDCap)", "count": 1 if flag("screening") else 0, "unit": PAY_SCREENING,
         "amount": PAY_SCREENING if flag("screening") else 0.0, "max": PAY_SCREENING,
         "note": None if rc.get("available") else "REDCap unavailable"},
        {"item": "Baseline interview (REDCap)", "count": 1 if flag("interview") else 0, "unit": PAY_INTERVIEW,
         "amount": PAY_INTERVIEW if flag("interview") else 0.0, "max": PAY_INTERVIEW,
         "note": None if rc.get("available") else "REDCap unavailable"},
        {"item": "Daily check-ins (within 4 h of prompt)", "count": ema["creditedPaid"], "unit": PAY_PER_EMA,
         "amount": round(ema["creditedPaid"] * PAY_PER_EMA, 2), "max": EMA_CAP * PAY_PER_EMA,
         "note": (f"{ema['credited'] - ema['creditedPaid']} over the cap" if ema["credited"] > EMA_CAP else None)},
        {"item": "Weekly app use (>=3 days & >=150 screenshots)", "count": app["paidWeeks"], "unit": PAY_PER_APP_WEEK,
         "amount": round(app["paidWeeks"] * PAY_PER_APP_WEEK, 2), "max": round(WEEK_PERIODS * PAY_PER_APP_WEEK, 2),
         "note": None},
        {"item": "Exit survey (REDCap)", "count": 1 if flag("exit") else 0, "unit": PAY_EXIT,
         "amount": PAY_EXIT if flag("exit") else 0.0, "max": PAY_EXIT,
         "note": None if rc.get("available") else "REDCap unavailable"},
        {"item": "Weekly REDCap surveys", "count": int(((rc.get("weekly") or {}).get("totalCompleted") or 0)),
         "unit": 0.0, "amount": 0.0, "max": 0.0, "note": "tracked, not compensated"},
        {"item": "Post-interview baseline battery", "count": int(((rc.get("baselineBattery") or {}).get("completed") or 0)),
         "unit": 0.0, "amount": 0.0, "max": 0.0,
         "note": f"of {len(REDCAP_BASELINE_FORMS)} instruments; tracked, not compensated"},
    ]
    earned = round(sum(l["amount"] for l in lines), 2)
    return {"lines": lines, "earned": earned, "maxPossible": round(MAX_POSSIBLE, 2), "rules": RULES}


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def report_to_csv(report: Dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    pid = report.get("participantId")
    w.writerow(["section", "participant", "item", "count", "unit", "amount", "max", "note"])
    for l in report["compensation"]["lines"]:
        w.writerow(["compensation", pid, l["item"], l["count"], l["unit"], l["amount"], l["max"], l["note"] or ""])
    w.writerow(["compensation", pid, "TOTAL EARNED TO DATE", "", "", report["compensation"]["earned"],
                report["compensation"]["maxPossible"], ""])
    w.writerow([])
    w.writerow(["week", "participant", "start", "end", "days", "active_days", "screenshots", "reddit", "twitter", "qualifies", "complete", "paid"])
    for wk in report["appUse"]["weeks"]:
        w.writerow(["app_week", pid, wk["start"], wk["end"], wk["days"], wk["activeDays"], wk["screenshots"],
                    wk["reddit"], wk["twitter"], wk["qualifies"], wk["complete"], wk["paid"]])
    w.writerow([])
    w.writerow(["day", "participant", "date", "prompt", "fired", "credited", "completed_at"])
    for d in report["ema"]["days"]:
        for p in d["prompts"]:
            w.writerow(["ema_day", pid, d["date"], p["time"], p["fired"], p["credited"], p["completedAt"] or ""])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Assembly (I/O)
# ---------------------------------------------------------------------------

def _daily_screenshots(participant_id: str, db, config, since_utc: datetime, tz) -> Dict[date, Dict[str, int]]:
    """Per local date: total / reddit / twitter screenshot counts. Reads only
    the few fields needed."""
    out: Dict[date, Dict[str, int]] = {}
    try:
        q = (db.collection(config.col("participants")).document(participant_id)
               .collection("events").where("timestamp", ">=", since_utc)
               .select(["timestamp", "eventType", "type", "platform", "capturedAt"]))
        for doc in q.stream():
            e = doc.to_dict() or {}
            if (e.get("eventType") or e.get("type")) != "screenshot":
                continue
            dt = _to_utc(e.get("capturedAt") or e.get("timestamp"))
            if not dt:
                continue
            d = dt.astimezone(tz).date()
            row = out.setdefault(d, {"total": 0, "reddit": 0, "twitter": 0})
            row["total"] += 1
            plat = str(e.get("platform") or "").lower()
            if "reddit" in plat:
                row["reddit"] += 1
            elif plat in ("twitter", "x") or "twitter" in plat:
                row["twitter"] += 1
    except Exception:
        pass
    return out


def build_compliance_report(participant_id: str, db, config, study_start: Optional[date],
                            record_id_resolver: Optional[Callable[[str], Optional[str]]] = None,
                            now: Optional[datetime] = None) -> Dict[str, Any]:
    """Assemble the whole report. Read-only."""
    from zoneinfo import ZoneInfo
    from participant_schedule import load_schedule, DEFAULT_TZ

    now_utc = now or datetime.now(timezone.utc)
    schedule = load_schedule(participant_id, db, config)
    tz_name = schedule.get("tz") or DEFAULT_TZ
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz_name, tz = DEFAULT_TZ, ZoneInfo(DEFAULT_TZ)
    today = now_utc.astimezone(tz).date()

    if study_start is None:
        return {"participantId": participant_id, "error": "No study start date on record",
                "available": False}

    since = datetime.combine(study_start - timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc)

    checkins = []
    try:
        q = (db.collection(config.col("participants")).document(participant_id)
               .collection("ema_responses").where("completedAt", ">=", since))
        checkins = [x.to_dict() or {} for x in q.stream()]
    except Exception:
        checkins = []

    ema = credit_emas(checkins, schedule, tz, study_start, today)
    app = weekly_app_use(_daily_screenshots(participant_id, db, config, since, tz), study_start, today)

    redcap: Dict[str, Any] = {"available": False, "reason": "no REDCap record mapped"}
    record_id = record_id_resolver(participant_id) if record_id_resolver else None
    if record_id:
        try:
            redcap = fetch_redcap_completions(record_id)
        except Exception as e:
            redcap = {"available": False, "reason": str(e), "recordId": record_id}

    return {
        "participantId": participant_id,
        "available": True,
        "studyStart": study_start.isoformat(),
        "studyEnd": (study_start + timedelta(days=STUDY_DAYS - 1)).isoformat(),
        "today": today.isoformat(),
        "studyDay": min(STUDY_DAYS, max(1, (today - study_start).days + 1)),
        "schedule": {"source": schedule.get("source"), "tz": tz_name, "promptTimes": schedule.get("current"),
                     "changes": [{"from": e["from"].isoformat(), "promptTimes": e["promptTimes"]} for e in schedule.get("timeline") or []]},
        "ema": ema,
        "appUse": app,
        "redcap": redcap,
        "compensation": compensation(ema, app, redcap),
        "generatedAt": now_utc.isoformat(),
    }
