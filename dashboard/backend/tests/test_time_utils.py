"""Unit tests for iso_utc — the Firestore-timestamp serializer for API responses.

Regression guard for the Communication History bug: a notification sent at
1:45 PM EDT rendered in the dashboard as "5:45 PM" and "-1d ago", because the
serialized string carried no timezone and the browser read it as local time.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from time_utils import iso_utc  # noqa: E402


class FirestoreTimestamp(datetime):
    """Stand-in for Firestore's DatetimeWithNanoseconds: a tz-aware subclass."""


class TestIsoUtc(unittest.TestCase):
    def test_always_marks_utc(self):
        # Without the trailing Z the browser parses this as local time.
        self.assertTrue(iso_utc(datetime(2026, 9, 25, 17, 45)).endswith("Z"))

    def test_naive_datetime_is_treated_as_utc(self):
        # datetime.utcnow() is what gets written to Firestore.
        self.assertEqual(iso_utc(datetime(2026, 9, 25, 17, 45)), "2026-09-25T17:45:00Z")

    def test_aware_datetime_converted_to_utc(self):
        eastern = timezone(timedelta(hours=-4))
        sent = datetime(2026, 9, 25, 13, 45, tzinfo=eastern)  # 1:45 PM EDT
        self.assertEqual(iso_utc(sent), "2026-09-25T17:45:00Z")

    def test_firestore_style_aware_subclass(self):
        ts = FirestoreTimestamp(2026, 9, 25, 17, 45, tzinfo=timezone.utc)
        self.assertEqual(iso_utc(ts), "2026-09-25T17:45:00Z")

    def test_no_double_shift_for_naive_value(self):
        # The old code ran fromtimestamp() on a naive value and shifted it by
        # the server's local offset. The instant must survive untouched.
        value = datetime(2026, 9, 25, 17, 45)
        self.assertEqual(iso_utc(value)[:19], value.isoformat()[:19])

    def test_epoch_numbers(self):
        self.assertEqual(iso_utc(0), "1970-01-01T00:00:00Z")

    def test_none_and_strings(self):
        self.assertIsNone(iso_utc(None))
        self.assertEqual(iso_utc("2026-09-25T17:45:00Z"), "2026-09-25T17:45:00Z")

    def test_object_with_broken_timestamp(self):
        class Broken:
            def timestamp(self):
                raise ValueError("nope")
        self.assertIsNone(iso_utc(Broken()))

    def test_roundtrips_to_the_same_instant(self):
        sent = datetime(2026, 9, 25, 17, 45, tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(iso_utc(sent).replace("Z", "+00:00"))
        self.assertEqual(parsed, sent)


if __name__ == "__main__":
    unittest.main()
