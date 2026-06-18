"""Unit tests for C-SSRS crisis detection (cssrs_sync).

These lock in the 2026-06-11 fix: the instrument and field names were ALL wrong
(crisis detection was completely dead). A regression that reverts any field name
or weakens the trigger rule would silently stop suicide-risk alerts — these tests
fail loudly if that happens.

Run:  python3 -m unittest discover -s dashboard/backend/tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cssrs_sync as c


class TestYesNoCoding(unittest.TestCase):
    def test_redcap_coding(self):
        self.assertIs(c._yn("1"), True)
        self.assertIs(c._yn("0"), False)
        self.assertIsNone(c._yn(""))
        self.assertIsNone(c._yn(None))
        # A stray non-0/1 string must NOT be treated as endorsed
        self.assertIsNone(c._yn("yes"))


class TestInstrumentNames(unittest.TestCase):
    """The exact REDCap form names — getting these wrong = dead detection."""
    def test_instrument_constants_match_redcap(self):
        self.assertEqual(c.CSSRS_SCREEN_INSTRUMENT, "cssrs_screener")
        self.assertEqual(c.CSSRS_WEEKLY_INSTRUMENT, "cssrs_weekly")
        self.assertEqual(c.CSSRS_PEDIATRIC_INSTRUMENT, "cssrs_pediatrics")
        self.assertEqual(
            set(c.CSSRS_INSTRUMENTS),
            {"cssrs_screener", "cssrs_weekly", "cssrs_pediatrics"},
        )

    def test_no_legacy_columbia_names(self):
        for v in (c.CSSRS_SCREEN_INSTRUMENT, c.CSSRS_PEDIATRIC_INSTRUMENT):
            self.assertNotIn("columbia", v)


class TestFieldMapsAreRealRedcapFields(unittest.TestCase):
    """Guard the exact field names verified against the live data dictionary."""
    def test_screener_fields(self):
        f = c.SCREEN_FIELDS
        self.assertEqual(f["ideation"], ["cssrs_scr_1", "cssrs_scr_2", "cssrs_scr_3", "cssrs_scr_4", "cssrs_scr_5"])
        self.assertEqual(f["behavior"], ["cssrs_scr_6a", "cssrs_scr_6b"])
        self.assertEqual(f["score"], "cssrs_scr_risk_score")
        # These do NOT exist in REDCap and must never reappear
        self.assertNotIn("cssrs_scr_6", f["ideation"] + f["behavior"])

    def test_weekly_fields_have_suffix(self):
        f = c.WEEKLY_FIELDS
        self.assertEqual(f["ideation"][3], "cssrs_scr_4cssrs_wkly")
        self.assertEqual(f["behavior"], ["cssrs_scr_6cssrs_wkly", "cssrs_scr_6_last3mcssrs_wkly"])

    def test_pediatric_fields(self):
        f = c.PEDIATRIC_FIELDS
        self.assertEqual(f["ideation"], ["cssrs_ped_1", "cssrs_ped_2", "cssrs_ped_3", "cssrs_ped_4", "cssrs_ped_5"])
        self.assertEqual(f["behavior"], ["cssrs_ped_6a", "cssrs_ped_6b", "cssrs_ped_6c", "cssrs_ped_6d"])


class TestCrisisTriggerFires(unittest.TestCase):
    """Crisis MUST trigger on intent (item 4), plan (item 5), or any behavior."""
    def test_screener_intent(self):
        self.assertTrue(c._transform_cssrs({"cssrs_scr_4": "1"}, "cssrs_screener")["crisisTriggered"])

    def test_screener_plan(self):
        self.assertTrue(c._transform_cssrs({"cssrs_scr_5": "1"}, "cssrs_screener")["crisisTriggered"])

    def test_screener_behavior_lifetime_and_recent(self):
        self.assertTrue(c._transform_cssrs({"cssrs_scr_6a": "1"}, "cssrs_screener")["crisisTriggered"])
        self.assertTrue(c._transform_cssrs({"cssrs_scr_6b": "1"}, "cssrs_screener")["crisisTriggered"])

    def test_weekly_plan_and_behavior(self):
        self.assertTrue(c._transform_cssrs({"cssrs_scr_5cssrs_wkly": "1"}, "cssrs_weekly")["crisisTriggered"])
        self.assertTrue(c._transform_cssrs({"cssrs_scr_6cssrs_wkly": "1"}, "cssrs_weekly")["crisisTriggered"])

    def test_pediatric_intent_and_each_behavior(self):
        self.assertTrue(c._transform_cssrs({"cssrs_ped_4": "1"}, "cssrs_pediatrics")["crisisTriggered"])
        for b in ("cssrs_ped_6a", "cssrs_ped_6b", "cssrs_ped_6c", "cssrs_ped_6d"):
            self.assertTrue(
                c._transform_cssrs({b: "1"}, "cssrs_pediatrics")["crisisTriggered"],
                f"behavior item {b} should trigger crisis",
            )


class TestCrisisTriggerDoesNotOverfire(unittest.TestCase):
    """Low-level ideation (items 1-3) and empty forms must NOT trigger."""
    def test_wish_to_be_dead_only(self):
        r = c._transform_cssrs({"cssrs_scr_1": "1"}, "cssrs_screener")
        self.assertFalse(r["crisisTriggered"])
        self.assertEqual(r["severity"], 1)

    def test_nonspecific_thoughts_only(self):
        r = c._transform_cssrs({"cssrs_ped_2": "1"}, "cssrs_pediatrics")
        self.assertFalse(r["crisisTriggered"])
        self.assertEqual(r["severity"], 2)

    def test_empty(self):
        r = c._transform_cssrs({}, "cssrs_screener")
        self.assertFalse(r["crisisTriggered"])
        self.assertEqual(r["severity"], 0)
        self.assertEqual(r["crisisTriggerFields"], [])

    def test_explicit_no_does_not_trigger(self):
        data = {f"cssrs_scr_{i}": "0" for i in range(1, 6)}
        data["cssrs_scr_6a"] = "0"
        data["cssrs_scr_6b"] = "0"
        self.assertFalse(c._transform_cssrs(data, "cssrs_screener")["crisisTriggered"])


class TestSeverity(unittest.TestCase):
    def test_highest_ideation_wins(self):
        self.assertEqual(c._transform_cssrs({"cssrs_scr_3": "1"}, "cssrs_screener")["severity"], 3)
        self.assertEqual(
            c._transform_cssrs({"cssrs_scr_2": "1", "cssrs_scr_4": "1"}, "cssrs_screener")["severity"], 4
        )

    def test_behavior_is_severity_6(self):
        r = c._transform_cssrs({"cssrs_scr_6b": "1"}, "cssrs_screener")
        self.assertEqual(r["severity"], 6)
        self.assertTrue(r["behaviorEndorsed"])


class TestTriggerFieldsReported(unittest.TestCase):
    def test_trigger_fields_listed(self):
        r = c._transform_cssrs({"cssrs_ped_4": "1", "cssrs_ped_6c": "1"}, "cssrs_pediatrics")
        self.assertIn("cssrs_ped_4", r["crisisTriggerFields"])
        self.assertIn("cssrs_ped_6c", r["crisisTriggerFields"])


class TestRiskAssessmentCompatShapes(unittest.TestCase):
    """risk_assessment.py imports these constants and reads these shapes."""
    def test_exported_constants_exist(self):
        self.assertTrue(hasattr(c, "CSSRS_CRISIS_TRIGGER_FIELDS"))
        self.assertTrue(hasattr(c, "CSSRS_SCREEN_LABELS"))
        # union must include screener intent/plan/behavior trigger fields
        for f in ("cssrs_scr_4", "cssrs_scr_5", "cssrs_scr_6a", "cssrs_scr_6b"):
            self.assertIn(f, c.CSSRS_CRISIS_TRIGGER_FIELDS)

    def test_screener_emits_questions_dict(self):
        q = c._transform_cssrs({"cssrs_scr_4": "1"}, "cssrs_screener")["questions"]
        self.assertIn("cssrs_scr_4", q)
        self.assertIs(q["cssrs_scr_4"]["value"], True)
        self.assertIn("label", q["cssrs_scr_4"])

    def test_pediatric_emits_named_ideation_and_behavior(self):
        r = c._transform_cssrs({"cssrs_ped_4": "1", "cssrs_ped_6c": "1"}, "cssrs_pediatrics")
        self.assertIs(r["ideation"]["ideation_with_intent"], True)
        self.assertIs(r["behavior"]["aborted_attempt"], True)


class TestRiskScoreParsing(unittest.TestCase):
    def test_numeric_score(self):
        r = c._transform_cssrs({"cssrs_scr_risk_score": "12"}, "cssrs_screener")
        self.assertEqual(r["riskScore"], 12)

    def test_blank_score_is_none(self):
        self.assertIsNone(c._transform_cssrs({}, "cssrs_screener")["riskScore"])


class TestBuildCssrsSafetyAlert(unittest.TestCase):
    def _build(self, instrument):
        return c.build_cssrs_safety_alert(
            participant_id="123456789", instrument=instrument, label="L",
            severity=5, crisis_trigger_fields=["x"], record_id="7",
            event_name="weekly_arm_1", now="T")

    def test_weekly_runs_full_confirmed_danger_protocol(self):
        d = self._build(c.CSSRS_WEEKLY_INSTRUMENT)
        # These two fields are what drive the full app protocol downstream.
        self.assertEqual(d["alertType"], "confirmed_danger")
        self.assertIs(d["confirmedDanger"], True)
        self.assertEqual(d["triggerSource"], "cssrs_weekly")

    def test_screener_does_NOT_run_full_protocol(self):
        d = self._build(c.CSSRS_SCREEN_INSTRUMENT)
        self.assertEqual(d["alertType"], "cssrs_crisis")
        self.assertIsNone(d["confirmedDanger"])
        self.assertNotIn("triggerSource", d)

    def test_pediatric_does_NOT_run_full_protocol(self):
        d = self._build(c.CSSRS_PEDIATRIC_INSTRUMENT)
        self.assertEqual(d["alertType"], "cssrs_crisis")
        self.assertIsNone(d["confirmedDanger"])

    def test_common_fields_preserved(self):
        d = self._build(c.CSSRS_WEEKLY_INSTRUMENT)
        self.assertEqual(d["participantId"], "123456789")
        self.assertEqual(d["redcapRecordId"], "7")
        self.assertEqual(d["redcapInstrument"], c.CSSRS_WEEKLY_INSTRUMENT)
        self.assertEqual(d["severity"], 5)
        self.assertFalse(d["handled"])


if __name__ == "__main__":
    unittest.main()
