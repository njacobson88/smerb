"""The overview must not serve its 14-day cache for a range it does not cover
(stepping back past the window showed blank rows for everyone, 2026-10-28)."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ENVIRONMENT", "prod")


class TestWindowWithinCache(unittest.TestCase):
    def setUp(self):
        from main import window_within_cache  # noqa
        self.f = window_within_cache

    def test_inside(self):
        self.assertTrue(self.f("2026-10-20", "2026-10-26", "2026-10-14", "2026-10-28"))

    def test_exact_bounds(self):
        self.assertTrue(self.f("2026-10-14", "2026-10-28", "2026-10-14", "2026-10-28"))

    def test_week_before_window_is_not_covered(self):
        self.assertFalse(self.f("2026-10-07", "2026-10-13", "2026-10-14", "2026-10-28"))

    def test_straddling_start_is_not_covered(self):
        self.assertFalse(self.f("2026-10-12", "2026-10-18", "2026-10-14", "2026-10-28"))

    def test_missing_bounds_means_not_covered(self):
        self.assertFalse(self.f("2026-10-20", "2026-10-26", None, None))


if __name__ == "__main__":
    unittest.main()
