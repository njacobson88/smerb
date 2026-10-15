"""The stale-mapping guard (incident 2026-10-14): a renamed record's number
gets reused by REDCap auto-numbering; the old mapping must never route a new
respondent's data — or a crisis alert — to the old participant."""
import logging
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from redcap_resolution import (  # noqa: E402
    decide, resolve_participant_for_record, mapping_reusable_at_qualify, MAPPING_SUPERSEDED_FIELD,
)


class FakeDoc:
    def __init__(self, data):
        self._d = data
    @property
    def exists(self):
        return self._d is not None
    def to_dict(self):
        return dict(self._d) if self._d is not None else None


class FakeRef:
    def __init__(self, store, key):
        self.store, self.key = store, key
    def get(self):
        return FakeDoc(self.store.get(self.key))
    def set(self, data, merge=False):
        cur = self.store.get(self.key) or {}
        self.store[self.key] = {**cur, **data} if merge else dict(data)


class FakeCol:
    def __init__(self, store):
        self.store = store
    def document(self, key):
        return FakeRef(self.store, key)


class FakeDb:
    def __init__(self):
        self.cols = {"redcap_mappings": {}, "participants": {}}
    def collection(self, name):
        return FakeCol(self.cols[name])


NOW = datetime(2026, 10, 14, 23, 23, 12)
LOG = logging.getLogger("test")


def run(db, record_id, app_id_by_record, fail=False):
    def fetch(rid):
        if fail:
            raise RuntimeError("REDCap down")
        return app_id_by_record.get(rid, "")
    return resolve_participant_for_record(
        record_id, db=db, mappings_collection="redcap_mappings",
        participants_collection="participants", fetch_record_app_id=fetch,
        logger=LOG, now=NOW, event_name="consent__screener_arm_1")


class TestDecide(unittest.TestCase):
    def test_table(self):
        self.assertEqual(decide("A", "A", True), ("A", "mapping_verified"))
        self.assertEqual(decide("A", "", True), (None, "stale_mapping"))        # the incident
        self.assertEqual(decide("A", "B", True), ("B", "stale_mapping"))        # re-pointed record
        self.assertEqual(decide(None, "B", True), ("B", "adopted_from_record"))  # rename repair
        self.assertEqual(decide(None, "", True), (None, "unresolved"))          # pre-qualify record
        self.assertEqual(decide("A", "A", False), (None, "lookup_failed"))      # never trust blindly


class TestIncidentReplay(unittest.TestCase):
    """Record 389: staff test record qualified -> mapping 389->184970972 ->
    record renamed test_rec_lc -> new respondent becomes 389 with no app id."""

    def setUp(self):
        self.db = FakeDb()
        self.db.cols["participants"]["184970972"] = {"name": "staff tester"}
        self.db.cols["redcap_mappings"]["389"] = {"app_participant_id": "184970972"}

    def test_new_respondent_on_reused_number_is_not_routed_to_old_participant(self):
        pid = run(self.db, "389", {"389": ""})          # new respondent, no app id
        self.assertIsNone(pid)
        m = self.db.cols["redcap_mappings"]["389"]
        self.assertEqual(m[MAPPING_SUPERSEDED_FIELD], NOW)
        self.assertEqual(m["superseded_app_participant_id"], "184970972")
        self.assertEqual(m["app_participant_id"], "184970972")  # kept as history, never deleted

    def test_superseded_mapping_stays_dead_on_later_saves(self):
        run(self.db, "389", {"389": ""})
        self.assertIsNone(run(self.db, "389", {"389": ""}))

    def test_renamed_record_still_resolves_via_its_app_id(self):
        # The staff tester's record now lives under its new name; no mapping yet.
        pid = run(self.db, "test_rec_lc", {"test_rec_lc": "184970972"})
        self.assertEqual(pid, "184970972")
        self.assertEqual(self.db.cols["redcap_mappings"]["test_rec_lc"]["app_participant_id"], "184970972")
        self.assertEqual(self.db.cols["participants"]["184970972"]["redcapRecordId"], "test_rec_lc")

    def test_reused_number_later_qualified_for_a_new_participant(self):
        self.db.cols["participants"]["555000111"] = {"name": "new participant"}
        pid = run(self.db, "389", {"389": "555000111"})
        self.assertEqual(pid, "555000111")
        m = self.db.cols["redcap_mappings"]["389"]
        self.assertEqual(m["app_participant_id"], "555000111")
        self.assertIsNone(m[MAPPING_SUPERSEDED_FIELD])


class TestOtherPaths(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        self.db.cols["participants"]["194203310"] = {}

    def test_verified_mapping_is_used(self):
        self.db.cols["redcap_mappings"]["194203310.BM"] = {"app_participant_id": "194203310"}
        self.assertEqual(run(self.db, "194203310.BM", {"194203310.BM": "194203310"}), "194203310")

    def test_redcap_outage_never_trusts_the_cache(self):
        self.db.cols["redcap_mappings"]["7"] = {"app_participant_id": "194203310"}
        self.assertIsNone(run(self.db, "7", {}, fail=True))
        self.assertNotIn(MAPPING_SUPERSEDED_FIELD, self.db.cols["redcap_mappings"]["7"])  # unknown, not stale

    def test_app_id_without_participant_doc_is_rejected(self):
        self.assertIsNone(run(self.db, "12", {"12": "000000000"}))
        self.assertNotIn("12", self.db.cols["redcap_mappings"])

    def test_pre_qualify_record_is_unresolved(self):
        self.assertIsNone(run(self.db, "390", {"390": ""}))


class TestQualifyReuse(unittest.TestCase):
    """At qualify the DET only calls when the record's app-id field is empty, so
    the cached mapping is the only thing that could hand out an id."""

    def test_reused_number_at_qualify_gets_a_fresh_id(self):
        # 389 -> staff tester, whose id now lives on record test_rec_lc.
        m = {"app_participant_id": "184970972"}
        self.assertIsNone(mapping_reusable_at_qualify(m, "389", "test_rec_lc"))

    def test_self_heal_still_works_when_write_back_failed(self):
        # Mapping exists, REDCap has the id on NO record (write-back failed).
        m = {"app_participant_id": "194203310"}
        self.assertEqual(mapping_reusable_at_qualify(m, "56", None), "194203310")
        self.assertEqual(mapping_reusable_at_qualify(m, "56", "56"), "194203310")

    def test_superseded_or_missing_mapping_is_never_reused(self):
        self.assertIsNone(mapping_reusable_at_qualify(None, "389", None))
        self.assertIsNone(mapping_reusable_at_qualify({"app_participant_id": "x", MAPPING_SUPERSEDED_FIELD: NOW}, "389", None))
        self.assertIsNone(mapping_reusable_at_qualify({"app_participant_id": ""}, "389", None))


if __name__ == "__main__":
    unittest.main()
