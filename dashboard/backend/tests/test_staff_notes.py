"""Unit tests for the study-personnel notes helpers.

The route bodies need Firestore, but the parts that decide what staff actually
see — ordering, revision history, category normalization — are pure.
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from staff_notes import (  # noqa: E402
    DEFAULT_CATEGORY,
    MAX_NOTE_LENGTH,
    NOTE_CATEGORIES,
    _normalize_category,
    serialize_note,
    sort_notes,
)


class FakeDoc:
    """Stands in for a Firestore DocumentSnapshot."""

    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


class TestSerializeNote(unittest.TestCase):
    def test_full_note(self):
        note = serialize_note(FakeDoc("abc", {
            "text": "Called participant, left voicemail.",
            "category": "contact",
            "pinned": True,
            "createdAt": datetime(2026, 9, 20, 14, 30),
            "createdBy": "coordinator@dartmouth.edu",
            "createdByName": "Study Coordinator",
            "revisions": [{"text": "Called participant.",
                           "editedAt": datetime(2026, 9, 20, 14, 35),
                           "editedBy": "coordinator@dartmouth.edu"}],
        }))
        self.assertEqual(note["id"], "abc")
        self.assertEqual(note["category"], "contact")
        self.assertTrue(note["pinned"])
        self.assertFalse(note["archived"])
        self.assertEqual(note["revisionCount"], 1)
        self.assertEqual(note["createdAt"], "2026-09-20T14:30:00Z")
        self.assertEqual(note["revisions"][0]["text"], "Called participant.")

    def test_sparse_note_does_not_explode(self):
        note = serialize_note(FakeDoc("xyz", {}))
        self.assertEqual(note["text"], "")
        self.assertEqual(note["category"], DEFAULT_CATEGORY)
        self.assertEqual(note["revisionCount"], 0)
        self.assertIsNone(note["createdAt"])

    def test_empty_document(self):
        note = serialize_note(FakeDoc("xyz", None))
        self.assertEqual(note["text"], "")


class TestSorting(unittest.TestCase):
    def note(self, note_id, created, pinned=False):
        return {"id": note_id, "pinned": pinned, "createdAt": created}

    def test_pinned_first_then_newest(self):
        notes = [
            self.note("old", "2026-09-01T00:00:00Z"),
            self.note("new", "2026-09-22T00:00:00Z"),
            self.note("pinned-old", "2026-08-01T00:00:00Z", pinned=True),
        ]
        self.assertEqual([n["id"] for n in sort_notes(notes)],
                         ["pinned-old", "new", "old"])

    def test_missing_timestamps_sort_last(self):
        notes = [self.note("undated", None), self.note("dated", "2026-09-22T00:00:00Z")]
        self.assertEqual([n["id"] for n in sort_notes(notes)], ["dated", "undated"])

    def test_empty_list(self):
        self.assertEqual(sort_notes([]), [])


class TestCategory(unittest.TestCase):
    def test_known_categories_pass_through(self):
        for category in NOTE_CATEGORIES:
            self.assertEqual(_normalize_category(category), category)

    def test_case_and_whitespace_tolerated(self):
        self.assertEqual(_normalize_category("  Clinical "), "clinical")

    def test_unknown_falls_back(self):
        self.assertEqual(_normalize_category("made-up"), DEFAULT_CATEGORY)
        self.assertEqual(_normalize_category(None), DEFAULT_CATEGORY)
        self.assertEqual(_normalize_category(""), DEFAULT_CATEGORY)


class TestNoDeleteRoute(unittest.TestCase):
    def test_module_exposes_no_delete(self):
        # Study policy: nothing in this project is ever deleted. Notes are
        # archived, and edits keep the prior text as a revision.
        import staff_notes
        with open(staff_notes.__file__) as f:
            source = f.read()
        self.assertNotIn("@app.delete", source)
        self.assertNotIn(".delete()", source)

    def test_note_length_is_bounded(self):
        self.assertLessEqual(MAX_NOTE_LENGTH, 100000)


if __name__ == "__main__":
    unittest.main()
