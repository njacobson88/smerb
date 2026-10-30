"""Per-participant daily summary cache: aggregation must match the old
endpoint exactly, and the incremental merge must never keep stale days."""
import os, sys, unittest
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daily_summary import (  # noqa: E402
    aggregate, merge_days, incremental_window, history_cutoff, empty_day,
    INCREMENTAL_LOOKBACK_DAYS, LIVE_TAIL_DAYS,
)


class TestAggregate(unittest.TestCase):
    def test_matches_endpoint_rules(self):
        events = [
            {"timestamp": "2026-10-29T10:00:00", "eventType": "screenshot", "platform": "reddit", "ocr": {"wordCount": 10}},
            {"timestamp": "2026-10-29T11:00:00", "eventType": "screenshot", "platform": "twitter"},
            {"timestamp": "2026-10-29T12:00:00", "eventType": "page_view", "platform": "reddit"},   # not a screenshot
            {"createdAt": "2026-10-30T09:00:00", "type": "screenshot", "platform": "unknown"},        # legacy keys
            {"eventType": "screenshot"},                                                             # no date -> skipped
        ]
        checkins = [
            {"completedAt": "2026-10-29T15:00:00", "responses": '{"ability_safe": "20", "crisis_now": "yes"}'},
            {"completedAt": "2026-10-30T15:00:00", "responses": {"desire": "no"}},
        ]
        alerts = [{"triggeredAt": "2026-10-29T15:01:00"}, {"triggeredAt": None}]
        d = aggregate(events, checkins, alerts)
        self.assertEqual(d["2026-10-29"], {"screenshots": 2, "ocr_words": 10, "ocr_chars": 50, "reddit": 1, "twitter": 1,
                                           "checkins": 1, "safety_alerts": 1, "crisis_indicated": True})
        self.assertEqual(d["2026-10-30"], {**empty_day(), "screenshots": 1, "checkins": 1})
        self.assertEqual(set(d), {"2026-10-29", "2026-10-30"})

    def test_empty(self):
        self.assertEqual(aggregate([], [], []), {})


class TestMerge(unittest.TestCase):
    def test_fresh_days_replace_and_stale_tail_is_dropped(self):
        cached = {"2026-10-20": {"screenshots": 5}, "2026-10-28": {"screenshots": 9}, "2026-10-29": {"screenshots": 1}}
        fresh = {"2026-10-28": {"screenshots": 11}}          # 10-29 has no events any more
        out = merge_days(cached, fresh, fresh_from="2026-10-28")
        self.assertEqual(out, {"2026-10-20": {"screenshots": 5}, "2026-10-28": {"screenshots": 11}})

    def test_fresh_days_before_window_are_ignored(self):
        out = merge_days({"2026-10-20": {"a": 1}}, {"2026-10-01": {"a": 9}}, "2026-10-28")
        self.assertEqual(out, {"2026-10-20": {"a": 1}})


class TestWindow(unittest.TestCase):
    NOW = datetime(2026, 10, 30, 21, 0)

    def test_first_run_is_full(self):
        self.assertIsNone(incremental_window(None, None, self.NOW))

    def test_incremental_looks_back(self):
        self.assertEqual(incremental_window("2026-10-28", self.NOW - timedelta(hours=1), self.NOW),
                         (datetime(2026, 10, 28) - timedelta(days=INCREMENTAL_LOOKBACK_DAYS - 1)).strftime("%Y-%m-%d"))

    def test_daily_full_rebuild(self):
        self.assertIsNone(incremental_window("2026-10-28", self.NOW - timedelta(hours=25), self.NOW))

    def test_history_cutoff_leaves_live_tail(self):
        self.assertEqual(history_cutoff(self.NOW), (self.NOW - timedelta(days=LIVE_TAIL_DAYS)).strftime("%Y-%m-%d"))


if __name__ == "__main__":
    unittest.main()
