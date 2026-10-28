"""A level-3 export whose worker died (OOM / scale-to-zero) must not show as
'processing' forever (2026-10-28, 1,753 screenshots, 1h45 'processing')."""
import os, sys, unittest
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ENVIRONMENT", "prod")


class TestStaleExportJob(unittest.TestCase):
    def setUp(self):
        from main import annotate_stale_export_job, EXPORT_JOB_STALE_MINUTES  # noqa
        self.f = annotate_stale_export_job; self.limit = EXPORT_JOB_STALE_MINUTES
        self.now = datetime(2026, 10, 28, 17, 27)

    def test_recent_processing_job_untouched(self):
        j = {"status": "processing", "startedAt": (self.now - timedelta(minutes=10)).isoformat() + "Z",
             "screenshotTotal": 1753, "screenshotProgress": 400, "timeEstimate": "~45 min remaining"}
        self.assertEqual(self.f(j, now=self.now), j)

    def test_old_processing_job_is_presented_as_failed(self):
        j = {"status": "processing", "startedAt": (self.now - timedelta(minutes=106)).isoformat() + "Z",
             "screenshotTotal": 1753, "screenshotProgress": 1753, "timeEstimate": "Calculating..."}
        out = self.f(j, now=self.now)
        self.assertEqual(out["status"], "failed"); self.assertTrue(out["staleDetected"])
        self.assertIn("1753/1753", out["error"]); self.assertNotIn("timeEstimate", out)
        self.assertEqual(j["status"], "processing")   # input not mutated

    def test_pending_without_start_uses_created(self):
        j = {"status": "pending", "createdAt": (self.now - timedelta(minutes=self.limit + 1)).isoformat() + "Z"}
        self.assertEqual(self.f(j, now=self.now)["status"], "failed")

    def test_completed_and_failed_untouched(self):
        for st in ("completed", "failed"):
            j = {"status": st, "startedAt": "2026-01-01T00:00:00Z"}
            self.assertEqual(self.f(j, now=self.now)["status"], st)

    def test_firestore_timestamp_objects_are_accepted(self):
        class TS:
            def __init__(self, dt): self._dt = dt
            def timestamp(self): return self._dt.timestamp()
        import calendar
        started = self.now - timedelta(minutes=200)
        class TSu(TS):
            def timestamp(self): return calendar.timegm(started.timetuple())
        self.assertEqual(self.f({"status": "processing", "startedAt": TSu(started)}, now=self.now)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
