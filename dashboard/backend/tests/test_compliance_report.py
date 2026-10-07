"""Tests for schedule inference, EMA crediting, weekly app-use qualification,
REDCap completion parsing and compensation math.

These guard the money: a credited EMA is $1 and a qualifying week is $1.50,
so the window edges and the thresholds must be exact.
"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from participant_schedule import DEFAULT_PROMPT_TIMES, infer_schedule, prompt_times_on  # noqa: E402
from compliance_report import (  # noqa: E402
    APP_WEEK_MIN_ACTIVE_DAYS, APP_WEEK_MIN_SCREENSHOTS, EMA_CAP, MAX_POSSIBLE,
    PAY_PER_APP_WEEK, PAY_PER_EMA, WEEK_PERIODS,
    compensation, credit_emas, parse_redcap_completions, report_to_csv,
    week_periods, weekly_app_use,
)

ET = ZoneInfo("America/New_York")
START = date(2026, 10, 3)
TODAY = date(2026, 10, 7)


def sched_row(day: date, t: str, tz="America/New_York"):
    return {"eventType": "ema_notification_scheduled",
            "data": {"timeOfDay": t, "firstFireAt": f"{day.isoformat()}T{t}:00.000-04:00", "tz": tz}}


def ci(d: date, hh: int, mm: int = 0):
    utc = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET).astimezone(timezone.utc)
    return {"completedAt": utc, "responses": {}}


class TestSchedule(unittest.TestCase):
    def test_default_when_nothing_logged(self):
        s = infer_schedule([])
        self.assertEqual(s["source"], "default")
        self.assertEqual(prompt_times_on(s, TODAY), list(DEFAULT_PROMPT_TIMES))

    def test_logged_schedule_and_tz(self):
        rows = [sched_row(START, t) for t in ("12:00", "16:00", "20:00")]
        s = infer_schedule(rows)
        self.assertEqual(s["source"], "logged")
        self.assertEqual(s["current"], ["12:00", "16:00", "20:00"])
        self.assertEqual(s["tz"], "America/New_York")

    def test_schedule_change_is_dated(self):
        rows = [sched_row(START, t) for t in ("10:00", "14:00", "18:00")]
        rows += [sched_row(START + timedelta(days=3), t) for t in ("11:00", "15:00", "19:00")]
        s = infer_schedule(rows)
        self.assertEqual(prompt_times_on(s, START + timedelta(days=1)), ["10:00", "14:00", "18:00"])
        self.assertEqual(prompt_times_on(s, START + timedelta(days=3)), ["11:00", "15:00", "19:00"])
        # Before the first log, the first logged schedule is used (not the default).
        self.assertEqual(prompt_times_on(s, START - timedelta(days=5)), ["10:00", "14:00", "18:00"])

    def test_partial_reschedule_does_not_create_a_new_schedule(self):
        rows = [sched_row(START, t) for t in ("11:00", "15:00", "19:00")]
        rows += [sched_row(START + timedelta(days=2), "15:00")]  # a single window re-armed
        s = infer_schedule(rows)
        self.assertEqual(len(s["timeline"]), 1)

    def test_bad_rows_ignored(self):
        rows = [{"eventType": "ema_notification_scheduled", "data": {"timeOfDay": "25:99"}},
                {"eventType": "other", "data": {"timeOfDay": "11:00"}}]
        self.assertEqual(infer_schedule(rows)["source"], "default")


class TestCreditEmas(unittest.TestCase):
    sched = infer_schedule([])  # 11/15/19

    def test_in_window_credits_once_per_window(self):
        d = START
        rows = [ci(d, 11, 5), ci(d, 12, 30), ci(d, 15, 1), ci(d, 20, 59)]
        r = credit_emas(rows, self.sched, ET, START, TODAY)
        self.assertEqual(r["credited"], 3)          # 11:05 (11), 15:01 (15), 20:59 (19)
        self.assertEqual(r["offWindow"], 1)         # 12:30 duplicates the 11:00 window
        self.assertEqual(r["completed"], 4)
        self.assertEqual(r["offWindowDetail"][0]["reason"], "window_already_credited")

    def test_window_edges(self):
        d = START
        # 14:59 is still inside the 11:00 window (< 15:00); 15:00 belongs to the 15:00 prompt.
        r = credit_emas([ci(d, 14, 59), ci(d, 15, 0)], self.sched, ET, START, TODAY)
        self.assertEqual(r["credited"], 2)
        # 23:00 is exactly 4 h after 19:00 -> outside.
        r2 = credit_emas([ci(d, 23, 0)], self.sched, ET, START, TODAY)
        self.assertEqual(r2["credited"], 0)
        self.assertEqual(r2["offWindowDetail"][0]["reason"], "no_prompt_within_window")

    def test_before_first_prompt_is_off_window(self):
        r = credit_emas([ci(START, 9, 0)], self.sched, ET, START, TODAY)
        self.assertEqual(r["credited"], 0)
        self.assertEqual(r["offWindow"], 1)

    def test_late_schedule_crosses_midnight(self):
        s = infer_schedule([sched_row(START, t) for t in ("13:00", "17:00", "21:00")])
        # 00:30 the next local day is inside the 21:00 window of the previous day.
        r = credit_emas([ci(START + timedelta(days=1), 0, 30)], s, ET, START, TODAY)
        self.assertEqual(r["credited"], 1)
        day0 = r["days"][0]
        self.assertTrue(any(p["time"] == "21:00" and p["credited"] for p in day0["prompts"]))

    def test_outside_study_period_is_ignored(self):
        r = credit_emas([ci(START - timedelta(days=1), 11, 5)], self.sched, ET, START, TODAY)
        self.assertEqual(r["completed"], 0)
        self.assertEqual(r["credited"], 0)

    def test_expected_counts_only_fired_prompts(self):
        r = credit_emas([], self.sched, ET, START, TODAY)
        self.assertEqual(len(r["days"]), (TODAY - START).days + 1)
        # Every day before today has all 3 fired; today depends on the clock.
        for day in r["days"][:-1]:
            self.assertEqual(day["expected"], 3)

    def test_paid_is_capped(self):
        rows = []
        for i in range(100):
            d = START + timedelta(days=i)
            rows += [ci(d, 11, 5), ci(d, 15, 5), ci(d, 19, 5)]
        r = credit_emas(rows, self.sched, ET, START, START + timedelta(days=200))
        self.assertEqual(r["credited"], EMA_CAP)       # 90 days x 3 = 270 within the study
        self.assertEqual(r["creditedPaid"], EMA_CAP)


class TestWeeklyAppUse(unittest.TestCase):
    def shots(self, by_day):
        return {START + timedelta(days=k): {"total": v, "reddit": v, "twitter": 0} for k, v in by_day.items()}

    def test_periods_cover_exactly_90_days(self):
        ps = week_periods(START)
        self.assertEqual(len(ps), WEEK_PERIODS)
        self.assertEqual(sum(p["days"] for p in ps), 90)
        self.assertEqual(ps[-1]["days"], 6)

    def test_threshold_edges(self):
        today = START + timedelta(days=30)
        # 3 active days & exactly 150 -> qualifies
        ok = weekly_app_use(self.shots({0: 50, 1: 50, 2: 50}), START, today)["weeks"][0]
        self.assertTrue(ok["qualifies"]); self.assertTrue(ok["paid"])
        # 149 screenshots -> no
        self.assertFalse(weekly_app_use(self.shots({0: 50, 1: 50, 2: 49}), START, today)["weeks"][0]["qualifies"])
        # 2 active days with 300 -> no
        self.assertFalse(weekly_app_use(self.shots({0: 150, 1: 150}), START, today)["weeks"][0]["qualifies"])
        self.assertEqual(APP_WEEK_MIN_ACTIVE_DAYS, 3)
        self.assertEqual(APP_WEEK_MIN_SCREENSHOTS, 150)

    def test_in_progress_week_is_on_track_not_paid(self):
        today = START + timedelta(days=3)
        w = weekly_app_use(self.shots({0: 60, 1: 60, 2: 60}), START, today)["weeks"][0]
        self.assertTrue(w["qualifies"]); self.assertFalse(w["complete"])
        self.assertFalse(w["paid"]); self.assertTrue(w["onTrack"])

    def test_platform_split(self):
        shots = {START: {"total": 10, "reddit": 7, "twitter": 3}}
        w = weekly_app_use(shots, START, START + timedelta(days=30))["weeks"][0]
        self.assertEqual((w["reddit"], w["twitter"]), (7, 3))


class TestRedcap(unittest.TestCase):
    def rows(self, screen="2", interview="2", exit_="0", battery_done=3):
        base = {"redcap_event_name": "postinterview_base_arm_1"}
        for i, f in enumerate(("idas_2", "phq_9", "gad_7")):
            base[f"{f}_complete"] = "2" if i < battery_done else "0"
        return [
            {"redcap_event_name": "consent__screener_arm_1", "cssrs_screener_complete": screen,
             "cssrs_screener_timestamp": "2026-09-20 10:00:00"},
            {"redcap_event_name": "interview_arm_1", "interview_questions_complete": interview,
             "interview_questions_timestamp": "2026-09-25 14:00:00"},
            {"redcap_event_name": "exit_arm_1", "exit_resources_complete": exit_},
            base,
        ]

    def test_completions(self):
        c = parse_redcap_completions(self.rows())
        self.assertTrue(c["screening"]["complete"]); self.assertIsNotNone(c["screening"]["at"])
        self.assertTrue(c["interview"]["complete"])
        self.assertFalse(c["exit"]["complete"]); self.assertIsNone(c["exit"]["at"])
        self.assertEqual(c["baselineBattery"]["completed"], 3)
        self.assertFalse(c["baselineBattery"]["complete"])

    def test_status_1_unverified_is_not_complete(self):
        c = parse_redcap_completions(self.rows(screen="1"))
        self.assertFalse(c["screening"]["complete"])


class TestCompensation(unittest.TestCase):
    def test_amounts_and_total(self):
        ema = {"credited": 12, "creditedPaid": 12}
        app = {"paidWeeks": 2}
        rc = {"available": True, "screening": {"complete": True}, "interview": {"complete": True},
              "exit": {"complete": False}, "weekly": {"totalCompleted": 2},
              "baselineBattery": {"completed": 17}}
        c = compensation(ema, app, rc)
        by = {l["item"]: l for l in c["lines"]}
        self.assertEqual(by["Screening (REDCap)"]["amount"], 10.0)
        self.assertEqual(by["Baseline interview (REDCap)"]["amount"], 20.0)
        self.assertEqual(by["Daily check-ins (within 4 h of prompt)"]["amount"], 12 * PAY_PER_EMA)
        self.assertEqual(by["Weekly app use (>=3 days & >=150 screenshots)"]["amount"], 2 * PAY_PER_APP_WEEK)
        self.assertEqual(by["Exit survey (REDCap)"]["amount"], 0.0)
        self.assertEqual(by["Weekly REDCap surveys"]["amount"], 0.0)
        self.assertEqual(c["earned"], 45.0)
        self.assertEqual(c["maxPossible"], round(MAX_POSSIBLE, 2))
        self.assertEqual(c["maxPossible"], 339.5)

    def test_redcap_unavailable_is_noted_not_paid(self):
        c = compensation({"credited": 0, "creditedPaid": 0}, {"paidWeeks": 0}, {"available": False})
        self.assertEqual(c["earned"], 0.0)
        self.assertEqual({l["item"]: l["note"] for l in c["lines"]}["Screening (REDCap)"], "REDCap unavailable")

    def test_csv_has_total_row(self):
        report = {"participantId": "p", "compensation": compensation({"credited": 1, "creditedPaid": 1}, {"paidWeeks": 0}, None),
                  "appUse": {"weeks": []}, "ema": {"days": []}}
        out = report_to_csv(report)
        self.assertIn("TOTAL EARNED TO DATE", out)
        self.assertIn("compensation,p,", out)


if __name__ == "__main__":
    unittest.main()
