"""Tests for the non-crisis SI trend flag.

The rule being guarded: flag "rising" only when the 7-day slope exceeds
+2/day AND the last-7 mean exceeds the prior-7 mean by >= 10, with enough
data; never on thin data; never for a first-week participant (no prior week).
"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from si_trend import (  # noqa: E402
    LEVEL_DELTA_MIN, MIN_CHECKINS_7D, MIN_DAYS_7D, SLOPE_MIN_PER_DAY,
    checkin_composite, compact, daily_means, trend_summary,
)

ET = ZoneInfo("America/New_York")
TODAY = date(2026, 10, 7)


def ci(day_offset, value, hour=12, scale="high_is_risk", **extra):
    """A check-in `day_offset` days before TODAY with all SI sliders at `value`."""
    d = TODAY - timedelta(days=day_offset)
    completed = datetime(d.year, d.month, d.day, hour, 0, tzinfo=ET).astimezone(timezone.utc)
    responses = {"desire_intensity": str(value), "intention_strength": str(value),
                 "ability_safe": str(value), "__ability_safe_scale": scale,
                 "thoughts_past_4hrs": "false"}
    responses.update(extra)
    return {"completedAt": completed, "responses": responses}


class TestComposite(unittest.TestCase):
    def test_mean_of_answered_items(self):
        r = {"desire_intensity": "40", "intention_strength": "20", "ability_safe": "60",
             "__ability_safe_scale": "high_is_risk", "thoughts_past_4hrs": "false"}
        # (40 + 20 + 60 + 0) / 4
        self.assertAlmostEqual(checkin_composite(r), 30.0)

    def test_ability_safe_old_scale_is_inverted(self):
        # Under the OLD scale (low_is_risk), 90 "able" = 10 risk.
        r = {"ability_safe": "90", "__ability_safe_scale": "low_is_risk"}
        self.assertAlmostEqual(checkin_composite(r), 10.0)

    def test_thoughts_past_4hrs_true_counts_as_100(self):
        r = {"desire_intensity": "0", "thoughts_past_4hrs": "true"}
        self.assertAlmostEqual(checkin_composite(r), 50.0)

    def test_unanswered_items_are_skipped_not_zeroed(self):
        self.assertAlmostEqual(checkin_composite({"intention_strength": "30"}), 30.0)
        self.assertIsNone(checkin_composite({}))
        self.assertIsNone(checkin_composite(None))

    def test_garbage_values_ignored(self):
        self.assertIsNone(checkin_composite({"desire_intensity": "abc", "intention_strength": "150"}))


class TestDailyMeans(unittest.TestCase):
    def test_groups_by_local_date(self):
        # 23:30 ET on day -1 is 03:30 UTC on day 0 — must land on day -1.
        rows = [ci(1, 10, hour=23), ci(0, 30, hour=9)]
        dm = daily_means(rows, ET)
        self.assertEqual(sorted(dm), [TODAY - timedelta(days=1), TODAY])
        # sliders 30/30/30 plus thoughts_past_4hrs=false (0) -> mean 22.5
        self.assertAlmostEqual(dm[TODAY]["mean"], 22.5)
        self.assertEqual(dm[TODAY]["n"], 1)


class TestRule(unittest.TestCase):
    def rising_week(self):
        # prior week flat at 10; last week climbing 20 -> 50 (slope +5/day), 2 check-ins/day
        rows = []
        for off in range(7, 14):
            rows += [ci(off, 10, hour=10), ci(off, 10, hour=18)]
        for i, off in enumerate(range(6, -1, -1)):
            v = 20 + 5 * i
            rows += [ci(off, v, hour=10), ci(off, v, hour=18)]
        return rows

    def test_rising_flags(self):
        s = trend_summary(daily_means(self.rising_week(), ET), TODAY)
        self.assertEqual(s["status"], "rising")
        self.assertGreater(s["slopePerDay"], SLOPE_MIN_PER_DAY)
        self.assertGreaterEqual(s["levelDelta"], LEVEL_DELTA_MIN)
        self.assertEqual(s["checkins7"], 14)
        self.assertEqual(s["days7"], 7)

    def test_steady_high_is_stable_not_rising(self):
        rows = [ci(off, 60, hour=h) for off in range(0, 14) for h in (10, 18)]
        s = trend_summary(daily_means(rows, ET), TODAY)
        self.assertEqual(s["status"], "stable")
        self.assertAlmostEqual(s["slopePerDay"], 0.0, places=5)

    def test_slope_without_level_change_is_stable(self):
        # Climbs within the week but the week's mean barely differs from prior.
        rows = [ci(off, 30, hour=h) for off in range(7, 14) for h in (10, 18)]
        for i, off in enumerate(range(6, -1, -1)):
            rows += [ci(off, 18 + 4 * i, hour=10), ci(off, 18 + 4 * i, hour=18)]  # mean 30, slope 4
        s = trend_summary(daily_means(rows, ET), TODAY)
        self.assertEqual(s["status"], "stable")
        self.assertLess(abs(s["levelDelta"]), LEVEL_DELTA_MIN)

    def test_level_jump_without_slope_is_stable(self):
        rows = [ci(off, 10, hour=h) for off in range(7, 14) for h in (10, 18)]
        rows += [ci(off, 50, hour=h) for off in range(0, 7) for h in (10, 18)]  # flat but higher
        s = trend_summary(daily_means(rows, ET), TODAY)
        self.assertEqual(s["status"], "stable")

    def test_thin_data_is_insufficient(self):
        rows = [ci(off, 10, hour=10) for off in range(7, 14)]
        rows += [ci(0, 90), ci(1, 80), ci(2, 70)]  # 3 check-ins, 3 days: below both minimums
        s = trend_summary(daily_means(rows, ET), TODAY)
        self.assertEqual(s["status"], "insufficient")
        self.assertLess(s["checkins7"], MIN_CHECKINS_7D)
        self.assertLess(s["days7"], MIN_DAYS_7D)

    def test_first_week_cannot_flag(self):
        rows = []
        for i, off in enumerate(range(6, -1, -1)):
            rows += [ci(off, 20 + 8 * i, hour=10), ci(off, 20 + 8 * i, hour=18)]
        s = trend_summary(daily_means(rows, ET), TODAY)
        self.assertTrue(s["noPriorWeek"])
        self.assertEqual(s["status"], "stable")  # strong slope, but no prior week to compare

    def test_series_is_14_days_with_gaps_as_none(self):
        s = trend_summary(daily_means([ci(0, 10)], ET), TODAY)
        self.assertEqual(len(s["series"]), 14)
        self.assertEqual(s["series"][-1]["date"], TODAY.isoformat())
        self.assertIsNone(s["series"][0]["mean"])

    def test_compact_has_only_overview_fields(self):
        s = trend_summary({}, TODAY)
        c = compact(s)
        self.assertEqual(set(c), {"status", "slopePerDay", "levelDelta", "last7Mean", "checkins7", "days7"})
        self.assertEqual(c["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
