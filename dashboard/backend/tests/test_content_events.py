"""Unit tests for the offloaded content-event read path (content_events.py).

These guard the 2026-06-12 storage optimization that moves content_visible /
content_exposure out of Firestore into gzipped-JSONL objects in Cloud Storage.
The export path reads them back; a decode/filter/dedup regression here would
silently drop research data from exports, so this is locked in.
"""
import gzip
import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import content_events as ce


def _gz(events):
    """Build a gzipped-JSONL object the way the app does."""
    text = "".join(json.dumps(e) + "\n" for e in events)
    return gzip.compress(text.encode("utf-8"))


SAMPLE = [
    {"id": "a1", "eventType": "content_visible", "timestamp": "2026-06-10T12:00:00.000Z"},
    {"id": "a2", "eventType": "content_exposure", "timestamp": "2026-06-11T09:30:00.000Z"},
    {"id": "a3", "eventType": "content_visible", "timestamp": "2026-06-12T23:59:00.000Z"},
]


class TestParseJsonlGz(unittest.TestCase):
    def test_roundtrip(self):
        out = ce.parse_jsonl_gz(_gz(SAMPLE))
        self.assertEqual([e["id"] for e in out], ["a1", "a2", "a3"])

    def test_corrupt_bytes_returns_empty(self):
        # The bug we fixed: GCS decompressive transcoding hands back already
        # decompressed bytes. Manual decompress must fail SOFT (skip, not crash).
        self.assertEqual(ce.parse_jsonl_gz(b"not gzip at all"), [])

    def test_skips_blank_and_malformed_lines(self):
        text = json.dumps(SAMPLE[0]) + "\n\n" + "{not json}\n" + json.dumps(SAMPLE[1]) + "\n"
        raw = gzip.compress(text.encode("utf-8"))
        out = ce.parse_jsonl_gz(raw)
        self.assertEqual([e["id"] for e in out], ["a1", "a2"])

    def test_empty_object(self):
        self.assertEqual(ce.parse_jsonl_gz(gzip.compress(b"")), [])


class TestEventInWindow(unittest.TestCase):
    def test_no_window_includes_all(self):
        self.assertTrue(ce.event_in_window(SAMPLE[0]))

    def test_inclusive_start_exclusive_end(self):
        start = datetime(2026, 6, 11)
        end = datetime(2026, 6, 12)  # backend adds +1 day to end_date; this is that bound
        kept = [e for e in SAMPLE if ce.event_in_window(e, start, end)]
        self.assertEqual([e["id"] for e in kept], ["a2"])

    def test_boundary_exact_start_included(self):
        ev = {"id": "x", "timestamp": "2026-06-11T00:00:00.000Z"}
        self.assertTrue(ce.event_in_window(ev, datetime(2026, 6, 11), datetime(2026, 6, 12)))

    def test_boundary_exact_end_excluded(self):
        ev = {"id": "x", "timestamp": "2026-06-12T00:00:00.000Z"}
        self.assertFalse(ce.event_in_window(ev, datetime(2026, 6, 11), datetime(2026, 6, 12)))

    def test_missing_timestamp_included_when_window_set(self):
        # Never silently drop research data we can't time-place.
        self.assertTrue(ce.event_in_window({"id": "x"}, datetime(2026, 6, 1), datetime(2026, 6, 2)))

    def test_unparseable_timestamp_included(self):
        ev = {"id": "x", "timestamp": "garbage"}
        self.assertTrue(ce.event_in_window(ev, datetime(2026, 6, 1), datetime(2026, 6, 2)))


class TestMergeContentEvents(unittest.TestCase):
    def test_appends_new(self):
        base = [{"id": "f1", "eventType": "screenshot"}]
        ce.merge_content_events(base, SAMPLE)
        self.assertEqual([e["id"] for e in base], ["f1", "a1", "a2", "a3"])

    def test_dedups_against_legacy_firestore_copy(self):
        # a2 already present from Firestore (transition window) — must not dupe.
        base = [{"id": "a2", "eventType": "content_exposure"}]
        ce.merge_content_events(base, SAMPLE)
        ids = [e["id"] for e in base]
        self.assertEqual(ids.count("a2"), 1)
        self.assertEqual(set(ids), {"a1", "a2", "a3"})

    def test_dedups_within_incoming(self):
        dupes = SAMPLE + [{"id": "a1", "eventType": "content_visible", "timestamp": "x"}]
        base = []
        ce.merge_content_events(base, dupes)
        self.assertEqual([e["id"] for e in base].count("a1"), 1)


if __name__ == "__main__":
    unittest.main()
