"""events.json is streamed into the zip one event at a time; the old list path
held every event twice in memory (2026-10-28)."""
import io, json, os, sys, unittest, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ENVIRONMENT", "prod")


class NoSeek(io.RawIOBase):
    """Stand-in for a GCS BlobWriter: write-only, not seekable."""
    def __init__(self): self.buf = bytearray()
    def writable(self): return True
    def seekable(self): return False
    def write(self, b): self.buf += b; return len(b)


class TestWriteEventsJsonStream(unittest.TestCase):
    def setUp(self):
        from main import write_events_json_stream, PARTICIPANT_METADATA_FIELDS  # noqa
        self.f = write_events_json_stream; self.fields = PARTICIPANT_METADATA_FIELDS

    def _run(self, fs_events, content, strip):
        sink = NoSeek()
        with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
            n, shots = self.f(zf, iter(fs_events), content, strip)
            zf.writestr(zipfile.ZipInfo("screenshots/x.jpg"), b"\xff\xd8", compress_type=zipfile.ZIP_STORED)
        z = zipfile.ZipFile(io.BytesIO(bytes(sink.buf)))
        self.assertIsNone(z.testzip())
        return n, shots, json.loads(z.read("events.json")), z.namelist()

    def test_order_dedup_and_screenshot_descriptors(self):
        fs = [("a", {"id": "a", "eventType": "screenshot", "screenshotUrl": "u1", "screenshotStoragePath": "p1", "timestamp": "t1"}),
              ("b", {"id": "b", "eventType": "page_view"})]
        content = [{"id": "b", "eventType": "content_visible"},   # duplicate of a Firestore copy -> skipped
                   {"id": "c", "eventType": "content_visible"}]
        n, shots, events, names = self._run(fs, content, strip=False)
        self.assertEqual([e["id"] for e in events], ["a", "b", "c"])
        self.assertEqual(n, 3)
        self.assertEqual(shots, [{"event_id": "a", "url": "u1", "storagePath": "p1", "timestamp": "t1"}])
        self.assertEqual(names, ["events.json", "screenshots/x.jpg"])

    def test_deidentified_strips_metadata_fields_per_event(self):
        field = next(iter(self.fields))
        fs = [("a", {"id": "a", field: "SECRET", "nested": {field: "SECRET", "keep": 1}})]
        _, _, events, _ = self._run(fs, [], strip=True)
        self.assertNotIn(field, events[0]); self.assertNotIn(field, events[0]["nested"])
        self.assertEqual(events[0]["nested"]["keep"], 1)

    def test_empty_inputs_give_empty_array(self):
        n, shots, events, _ = self._run([], [], strip=False)
        self.assertEqual((n, shots, events), (0, [], []))


if __name__ == "__main__":
    unittest.main()
