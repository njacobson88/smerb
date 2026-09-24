"""Unit tests for weekly-survey completion + reminder derivation from REDCap.

These run against fixtures shaped like real `weekly_survey_arm_1` exports, so the
7-day window logic can be exercised without hitting the live project.
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from redcap_weekly import (  # noqa: E402
    WEEKLY_SURVEY_INSTRUMENTS,
    REMINDER_FIELDS,
    parse_redcap_timestamp,
    parse_choices,
    strip_html,
    summarize_reminders,
    summarize_weekly_survey,
    summarize_weekly_survey_instance,
)

NOW = datetime(2026, 9, 24, 12, 0, 0)


def instance_row(number, day, completed_instruments=None, event="weekly_survey_arm_1"):
    """Build a repeat-instance row; by default the whole battery is finished."""
    done = WEEKLY_SURVEY_INSTRUMENTS if completed_instruments is None else completed_instruments
    row = {
        "record_id": "194203310.BM",
        "redcap_event_name": event,
        "redcap_repeat_instance": number,
    }
    for instrument in WEEKLY_SURVEY_INSTRUMENTS:
        if instrument in done:
            row[f"{instrument}_complete"] = "2"
            row[f"{instrument}_timestamp"] = f"{day} 11:45:00"
        else:
            row[f"{instrument}_complete"] = "0"
            row[f"{instrument}_timestamp"] = ""
    return row


class TestTimestampParsing(unittest.TestCase):
    def test_parses_to_utc(self):
        # 2026-09-21 is EDT (UTC-4), so noon local is 16:00 UTC.
        parsed = parse_redcap_timestamp("2026-09-21 12:00:00")
        self.assertEqual(parsed.hour, 16)
        self.assertEqual(parsed.date(), datetime(2026, 9, 21).date())

    def test_not_completed_sentinel_is_not_a_time(self):
        self.assertIsNone(parse_redcap_timestamp("[not completed]"))

    def test_blank_and_non_string(self):
        self.assertIsNone(parse_redcap_timestamp(""))
        self.assertIsNone(parse_redcap_timestamp(None))
        self.assertIsNone(parse_redcap_timestamp(12345))


class TestInstanceSummary(unittest.TestCase):
    def test_full_battery_is_complete(self):
        s = summarize_weekly_survey_instance(instance_row(2, "2026-09-21"))
        self.assertTrue(s["complete"])
        self.assertEqual(s["status"], "completed")
        self.assertEqual(s["instrumentsCompleted"], len(WEEKLY_SURVEY_INSTRUMENTS))

    def test_first_instrument_only_is_partial(self):
        s = summarize_weekly_survey_instance(
            instance_row(2, "2026-09-18", completed_instruments=["phq_9"]))
        self.assertFalse(s["complete"])
        self.assertEqual(s["status"], "partial")
        self.assertEqual(s["instrumentsCompleted"], 1)
        self.assertIsNone(s["completedAt"])

    def test_final_instrument_alone_counts_as_finished(self):
        # wkly_resources is served last; reaching it means they got through.
        s = summarize_weekly_survey_instance(
            instance_row(3, "2026-09-22", completed_instruments=["wkly_resources"]))
        self.assertTrue(s["complete"])
        self.assertIsNotNone(s["completedAt"])


class TestWeeklyWindow(unittest.TestCase):
    def test_completed_inside_window(self):
        rows = [instance_row(1, "2026-09-11"), instance_row(2, "2026-09-21")]
        s = summarize_weekly_survey(rows, now=NOW)
        self.assertEqual(s["status"], "completed")
        self.assertTrue(s["completedInWindow"])
        self.assertEqual(s["currentInstance"], 2)
        self.assertEqual(s["totalCompleted"], 2)
        self.assertIn("Sep 21", s["weekly_survey_line"])

    def test_completed_only_outside_window(self):
        rows = [instance_row(1, "2026-09-11")]
        s = summarize_weekly_survey(rows, now=NOW)
        self.assertEqual(s["status"], "none")
        self.assertFalse(s["completedInWindow"])
        # Their historical completion is still reported, just not as "this week".
        self.assertIsNotNone(s["lastCompletedAt"])
        self.assertEqual(s["weekly_survey_status"], "Not completed")

    def test_started_but_unfinished_inside_window(self):
        rows = [instance_row(2, "2026-09-18", completed_instruments=["phq_9"])]
        s = summarize_weekly_survey(rows, now=NOW)
        self.assertEqual(s["status"], "partial")
        self.assertTrue(s["startedInWindow"])
        self.assertFalse(s["completedInWindow"])
        self.assertIn("1 of 11", s["weekly_survey_line"])

    def test_no_weekly_data_at_all(self):
        s = summarize_weekly_survey([], now=NOW)
        self.assertEqual(s["status"], "none")
        self.assertIsNone(s["lastCompletedAt"])
        self.assertEqual(s["instances"], [])
        self.assertIn("Not completed", s["weekly_survey_line"])

    def test_other_events_are_ignored(self):
        rows = [instance_row(1, "2026-09-21", event="postinterview_base_arm_1")]
        s = summarize_weekly_survey(rows, now=NOW)
        self.assertEqual(s["status"], "none")

    def test_instances_are_newest_first(self):
        rows = [instance_row(1, "2026-09-11"), instance_row(3, "2026-09-22"),
                instance_row(2, "2026-09-18")]
        s = summarize_weekly_survey(rows, now=NOW)
        self.assertEqual([i["instance"] for i in s["instances"]], [3, 2, 1])

    def test_email_variables_always_present(self):
        for rows in ([], [instance_row(1, "2026-09-21")],
                     [instance_row(1, "2026-09-21", completed_instruments=["phq_9"])]):
            s = summarize_weekly_survey(rows, now=NOW)
            for key in ("weekly_survey_status", "weekly_survey_detail", "weekly_survey_line"):
                self.assertIn(key, s)
                self.assertTrue(s[key])

    def test_internal_keys_are_not_serialized(self):
        s = summarize_weekly_survey([instance_row(1, "2026-09-21")], now=NOW)
        for inst in s["instances"]:
            self.assertFalse([k for k in inst if k.startswith("_")])


class TestReminders(unittest.TestCase):
    def test_empty_record_lists_every_switch_as_unset(self):
        s = summarize_reminders(None)
        self.assertFalse(s["hasData"])
        self.assertEqual(s["setCount"], 0)
        self.assertEqual(len(s["reminders"]), len(REMINDER_FIELDS))
        self.assertTrue(all(r["valueLabel"] == "Not set" for r in s["reminders"]))

    def test_send_and_cancel_are_distinguished(self):
        s = summarize_reminders({
            "reminder_wkly": "1",
            "reminder_exit": "0",
            "reminders_complete": "2",
            "reminders_timestamp": "2026-09-20 09:00:00",
        })
        by_field = {r["field"]: r for r in s["reminders"]}
        self.assertTrue(by_field["reminder_wkly"]["send"])
        self.assertEqual(by_field["reminder_wkly"]["valueLabel"], "Send")
        self.assertTrue(by_field["reminder_exit"]["cancelled"])
        self.assertEqual(by_field["reminder_exit"]["valueLabel"], "Cancel")
        self.assertEqual(s["setCount"], 2)
        self.assertTrue(s["hasData"])
        self.assertIsNotNone(s["updatedAt"])

    def test_redcap_labels_override_static_fallback(self):
        s = summarize_reminders({"reminder_wkly": "1"},
                                labels={"reminder_wkly": "Weekly nudge (renamed)"})
        self.assertEqual(s["reminders"][0]["label"], "Weekly nudge (renamed)")

    def test_unknown_code_falls_back_to_raw_value(self):
        s = summarize_reminders({"reminder_wkly": "7"})
        self.assertEqual(s["reminders"][0]["valueLabel"], "7")
        self.assertFalse(s["reminders"][0]["send"])


class TestMetadataParsing(unittest.TestCase):
    def test_strip_html(self):
        self.assertEqual(
            strip_html('<div class="rich-text-field-label"><p>ELIGIBLE</p></div>'),
            "ELIGIBLE")

    def test_parse_choices(self):
        self.assertEqual(parse_choices("1, Send | 0, Cancel"),
                         {"1": "Send", "0": "Cancel"})

    def test_parse_choices_tolerates_trailing_comma(self):
        # `participant_welcome_manual` is literally defined as "1, Send, | 0, Cancel".
        self.assertEqual(parse_choices("1, Send, | 0, Cancel"),
                         {"1": "Send", "0": "Cancel"})


if __name__ == "__main__":
    unittest.main()
