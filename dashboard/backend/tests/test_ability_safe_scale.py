"""ability_safe was reversed mid-study (high now = riskier).

Old responses must keep being read on the OLD scale forever, and the scale must
never be inferred from a date — only from the marker the app recorded.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ema_scale import (
    ability_safe_high_is_risk, ability_safe_risk_value, compute_ema_risk_score,
    ABILITY_SAFE_SCALE_KEY, ABILITY_SAFE_HIGH_IS_RISK, EMA_THRESHOLD,
)

NEW = {ABILITY_SAFE_SCALE_KEY: ABILITY_SAFE_HIGH_IS_RISK}


class TestScaleDetection(unittest.TestCase):
    def test_unmarked_is_old_scale(self):
        self.assertFalse(ability_safe_high_is_risk({"ability_safe": 17}))

    def test_marked_is_new_scale(self):
        self.assertTrue(ability_safe_high_is_risk({**NEW, "ability_safe": 83}))

    def test_empty(self):
        self.assertFalse(ability_safe_high_is_risk({}))
        self.assertFalse(ability_safe_high_is_risk(None))


class TestRiskUnits(unittest.TestCase):
    def test_old_scale_inverts(self):
        # 17 on the old scale = barely able to stay safe = high risk
        self.assertEqual(ability_safe_risk_value({"ability_safe": 17}), 83)

    def test_new_scale_passes_through(self):
        self.assertEqual(ability_safe_risk_value({**NEW, "ability_safe": 83}), 83)

    def test_equivalent_answers_agree(self):
        """The same participant, before and after the flip, scores the same."""
        self.assertEqual(
            ability_safe_risk_value({"ability_safe": 17}),
            ability_safe_risk_value({**NEW, "ability_safe": 83}),
        )

    def test_able_participant_low_risk_both_scales(self):
        self.assertEqual(ability_safe_risk_value({"ability_safe": 95}), 5)
        self.assertEqual(ability_safe_risk_value({**NEW, "ability_safe": 5}), 5)

    def test_missing_or_bad(self):
        self.assertIsNone(ability_safe_risk_value({}))
        self.assertIsNone(ability_safe_risk_value({"ability_safe": "n/a"}))


class TestCompositeScore(unittest.TestCase):
    def test_old_scale_low_ability_drives_score(self):
        r = {"ability_safe": 17, "desire_intensity": 10}
        self.assertEqual(compute_ema_risk_score(r), 83)

    def test_new_scale_high_value_drives_score(self):
        r = {**NEW, "ability_safe": 83, "desire_intensity": 10}
        self.assertEqual(compute_ema_risk_score(r), 83)

    def test_able_participant_not_flagged_either_scale(self):
        self.assertEqual(compute_ema_risk_score({"ability_safe": 95}), 5)
        self.assertEqual(compute_ema_risk_score({**NEW, "ability_safe": 5}), 5)

    def test_other_items_unaffected_by_marker(self):
        self.assertEqual(compute_ema_risk_score({**NEW, "desire_intensity": 60}), 60)
        self.assertEqual(compute_ema_risk_score({"desire_intensity": 60}), 60)

    def test_regression_real_participant(self):
        """194203310 answered 17 pre-flip; must still read as high risk."""
        self.assertGreaterEqual(compute_ema_risk_score({"ability_safe": 16.95}), EMA_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
