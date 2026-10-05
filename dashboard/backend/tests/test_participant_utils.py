"""Regression tests for study-start resolution across the two participant docs.

The bug these guard: calculate_participant_compliance iterated
valid_participants THEN participants, so `participants.createdAt` overwrote the
researcher-set `valid_participants.studyStartDate`. A participant whose study
started 2026-10-03 was shown as owing check-ins for 2026-10-02.
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from participant_utils import (  # noqa: E402
    fetch_merged_participant,
    merge_participant_docs,
    resolve_study_start,
)


class Ts:
    """Stand-in for a Firestore timestamp (has .timestamp())."""
    def __init__(self, dt):
        self._dt = dt.replace(tzinfo=timezone.utc)

    def timestamp(self):
        return self._dt.timestamp()


class FakeDoc:
    def __init__(self, data):
        self.exists = data is not None
        self._data = data

    def to_dict(self):
        return self._data


class FakeDb:
    """collection(name).document(id).get() -> FakeDoc from a nested dict."""
    def __init__(self, store):
        self._store = store

    def collection(self, name):
        store = self._store
        class _Coll:
            def document(self, pid):
                class _Ref:
                    def get(_self):
                        return FakeDoc(store.get(name, {}).get(pid))
                return _Ref()
        return _Coll()


class TestMerge(unittest.TestCase):
    def test_overlay_wins_on_non_none(self):
        self.assertEqual(
            merge_participant_docs({"a": 1, "b": 1}, {"a": 2, "b": None}),
            {"a": 2, "b": 1})

    def test_handles_none_inputs(self):
        self.assertEqual(merge_participant_docs(None, None), {})
        self.assertEqual(merge_participant_docs({"a": 1}, None), {"a": 1})


class TestResolveStudyStart(unittest.TestCase):
    def test_researcher_set_date_wins_over_everything(self):
        data = {"studyStartDate": "2026-10-03",
                "enrolledAt": Ts(datetime(2026, 10, 2, 18, 56)),
                "createdAt": Ts(datetime(2026, 10, 2, 18, 56))}
        self.assertEqual(resolve_study_start(data).date(), datetime(2026, 10, 3).date())

    def test_falls_back_to_enrollment_then_creation(self):
        self.assertEqual(
            resolve_study_start({"enrolledAt": "2026-09-01"}).date(), datetime(2026, 9, 1).date())
        self.assertEqual(
            resolve_study_start({"createdAt": "2026-09-05"}).date(), datetime(2026, 9, 5).date())

    def test_explicit_fallback_sits_between_enrollment_and_creation(self):
        self.assertEqual(
            resolve_study_start({"createdAt": "2026-09-05"}, fallback="2026-09-04").date(),
            datetime(2026, 9, 4).date())

    def test_unparseable_string_is_skipped_not_fatal(self):
        self.assertEqual(
            resolve_study_start({"studyStartDate": "not a date", "createdAt": "2026-09-05"}).date(),
            datetime(2026, 9, 5).date())

    def test_nothing_usable_returns_none(self):
        self.assertIsNone(resolve_study_start({}))
        self.assertIsNone(resolve_study_start(None))


class TestFetchMerged(unittest.TestCase):
    def test_the_exact_production_bug(self):
        # participants has only createdAt (10/02); valid_participants carries
        # the researcher-set studyStartDate (10/03). The merge must yield 10/03.
        db = FakeDb({
            "participants": {"693493543": {"createdAt": Ts(datetime(2026, 10, 2, 18, 56))}},
            "valid_participants": {"693493543": {"studyStartDate": "2026-10-03"}},
        })
        merged = fetch_merged_participant(db, "693493543", ("participants", "valid_participants"))
        self.assertEqual(resolve_study_start(merged).date(), datetime(2026, 10, 3).date())

    def test_last_collection_wins_on_conflicts(self):
        db = FakeDb({
            "participants": {"p": {"studyStartDate": "2026-01-01", "phone": "111"}},
            "valid_participants": {"p": {"studyStartDate": "2026-02-02"}},
        })
        merged = fetch_merged_participant(db, "p", ("participants", "valid_participants"))
        self.assertEqual(merged["studyStartDate"], "2026-02-02")
        self.assertEqual(merged["phone"], "111")  # non-conflicting fields survive

    def test_missing_everywhere_is_none(self):
        self.assertIsNone(fetch_merged_participant(FakeDb({}), "x", ("participants", "valid_participants")))


if __name__ == "__main__":
    unittest.main()
