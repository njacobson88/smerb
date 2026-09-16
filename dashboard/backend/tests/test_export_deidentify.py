"""Exporting without participant metadata must actually de-identify.

Dropping participant_metadata.json alone is not enough — the participant id and
contact details also appear inside events, check-ins, alerts and notification
logs, so they have to be stripped from every record too.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load():
    """Import the helpers without pulling in FastAPI (not installed here)."""
    import re
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")).read()
    start = src.index("PARTICIPANT_METADATA_FIELDS = {")
    end = src.index("EXPORT_DEIDENTIFIED_README")
    ns = {}
    exec(src[start:end], ns)
    return ns["PARTICIPANT_METADATA_FIELDS"], ns["strip_participant_metadata"]


FIELDS, strip = _load()


class TestStrip(unittest.TestCase):
    def test_removes_participant_id(self):
        self.assertNotIn("participantId", strip({"participantId": "194203310", "x": 1}))

    def test_keeps_measurement_data(self):
        out = strip({"participantId": "1", "responses": {"hopeless": 40}, "completedAt": "t"})
        self.assertEqual(out, {"responses": {"hopeless": 40}, "completedAt": "t"})

    def test_removes_contact_details(self):
        out = strip({"name": "A B", "phone": "555", "email": "a@b.c",
                     "address": "1 St", "county": "X", "emergencyContacts": [{"phone": "9"}],
                     "sessionId": "keep"})
        self.assertEqual(out, {"sessionId": "keep"})

    def test_nested_and_lists(self):
        rows = [{"participantId": "1", "data": {"participantId": "1", "v": 2}}]
        self.assertEqual(strip(rows), [{"data": {"v": 2}}])

    def test_no_identifier_survives_anywhere(self):
        rows = [{"participantId": "194203310", "phone": "(216) 555",
                 "nested": {"redcapRecordId": "194203310.BM", "ok": 1}}]
        blob = repr(strip(rows))
        self.assertNotIn("194203310", blob)
        self.assertNotIn("216", blob)
        self.assertIn("ok", blob)

    def test_scalars_passthrough(self):
        self.assertEqual(strip("x"), "x")
        self.assertEqual(strip(5), 5)
        self.assertIsNone(strip(None))


if __name__ == "__main__":
    unittest.main()
