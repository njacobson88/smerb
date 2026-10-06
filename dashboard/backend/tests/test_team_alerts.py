"""Tests for the Slack team-alert and resolution-notice composition.

What must not regress (2026-10-05 incident): a walk-away must never be
described to the team as a confirmed crisis, and Slack must never get an
all-clear for an event it was never told about.
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from team_alerts import (  # noqa: E402
    ALERT_LABELS,
    compose_resolution,
    compose_team_alert,
)

NOW = datetime(2026, 10, 5, 23, 48, 11, tzinfo=timezone.utc)


def event(alert_type, **extra):
    base = {"participantId": "939703009", "alertId": "a44f_walkaway", "alertType": alert_type,
            "createdAt": NOW, "participantPhone": "(614) 886-1952",
            "responses": {"intention_strength": "44.0", "desire_intensity": "0.0"},
            "triggerQuestion": "intention_strength"}
    base.update(extra)
    return base


AUDIT = [
    {"type": "alert_created", "loggedAt": NOW},
    {"type": "participant_sms_sent", "loggedAt": NOW},
    {"type": "participant_push_sent", "loggedAt": NOW},
    {"type": "participant_email_sent", "loggedAt": NOW},
    {"type": "participant_call_initiated", "loggedAt": NOW},
]


class TestTeamAlertWording(unittest.TestCase):
    def test_walkaway_is_explicitly_not_confirmed(self):
        subj, body = compose_team_alert(event("unresolved_walkaway"), None, AUDIT, 15, "Leila Capel")
        self.assertIn("POTENTIAL RISK — NOT confirmed", subj)
        self.assertIn("NOT confirmed danger", body)
        self.assertNotIn("endorsed imminent", body)
        self.assertNotIn("CONFIRMED", body.split("\n")[0])

    def test_incomplete_is_explicitly_not_confirmed(self):
        subj, body = compose_team_alert(event("incomplete_checkin_fallback"), None, AUDIT, 15, None)
        self.assertIn("NOT confirmed", subj)
        self.assertIn("NOT confirmed danger", body)

    def test_confirmed_says_confirmed(self):
        subj, body = compose_team_alert(event("confirmed_danger"), None, AUDIT, 15, "Leila Capel")
        self.assertIn("CONFIRMED DANGER", subj)
        self.assertIn("CONFIRMED in the app", body)

    def test_subject_carries_minutes_unresolved_and_participant(self):
        subj, _ = compose_team_alert(event("unresolved_walkaway"), None, AUDIT, 15.4, None)
        self.assertIn("unresolved 15 min", subj)
        self.assertIn("939703009", subj)

    def test_lists_outreach_already_done_and_who_was_paged(self):
        _, body = compose_team_alert(event("unresolved_walkaway"), None, AUDIT, 15, "Leila Capel")
        for line in ("Text sent", "App notification sent", "Email sent", "Automated call placed"):
            self.assertIn(line, body)
        self.assertIn("On-call paged now: Leila Capel", body)
        self.assertIn("Reply ACK", body)
        self.assertIn("attached", body)

    def test_trigger_values_are_shown(self):
        _, body = compose_team_alert(event("unresolved_walkaway"), None, AUDIT, 15, None)
        self.assertIn("intention_strength = 44/100", body)

    def test_alert_doc_trigger_list_wins_when_present(self):
        alert = {"triggerQuestions": ["ability_safe"], "responses": {"ability_safe": "100.0"},
                 "thresholdExceededAt": NOW}
        _, body = compose_team_alert(event("unresolved_walkaway"), alert, AUDIT, 15, None)
        self.assertIn("ability_safe = 100/100", body)

    def test_no_phone_is_called_out(self):
        _, body = compose_team_alert(event("unresolved_walkaway", participantPhone=None), None, [], 15, None)
        self.assertIn("NO PHONE ON FILE", body)

    def test_missing_primary_is_called_out_not_hidden(self):
        _, body = compose_team_alert(event("unresolved_walkaway"), None, AUDIT, 15, None)
        self.assertIn("no primary on the roster", body)

    def test_every_known_type_has_a_label(self):
        for t in ("confirmed_danger", "unresolved_walkaway", "incomplete_checkin_fallback"):
            self.assertIn(t, ALERT_LABELS)


class TestResolutionWording(unittest.TestCase):
    def test_participant_paths(self):
        for via, expect in (("sms", "replied ERROR by text"),
                            ("ivr_press1_error", "pressed 1"),
                            ("ivr_press3_resolved", "pressed 3"),
                            ("app_push_error", "tapped 'error'")):
            subj, body = compose_resolution(event("unresolved_walkaway"), via)
            self.assertIn("[RESOLVED]", subj, via)
            self.assertIn(expect, body, via)

    def test_988_connection_is_not_called_resolved(self):
        subj, body = compose_resolution(event("confirmed_danger"), "bridge_988")
        self.assertIn("[CONNECTED TO 988]", subj)
        self.assertNotIn("[RESOLVED]", subj)
        self.assertIn("connected to 988", body)

    def test_staff_dispositions_name_the_person(self):
        subj, body = compose_resolution(event("unresolved_walkaway"), "oncall_sms:contacted_safe", "Leila Capel")
        self.assertIn("[RESOLVED]", subj)
        self.assertIn('Leila Capel logged the outcome "Safe" by text', body)
        subj2, body2 = compose_resolution(event("unresolved_walkaway"), "dashboard:false_alarm", "nick@dartmouth.edu")
        self.assertIn('nick@dartmouth.edu logged the outcome "False alarm" on the dashboard', body2)

    def test_staff_escalations_are_tagged_escalated(self):
        subj, _ = compose_resolution(event("confirmed_danger"), "oncall_sms:escalated_er", "Leila")
        self.assertIn("[ESCALATED]", subj)

    def test_ack_and_ongoing_are_not_resolutions(self):
        self.assertIsNone(compose_resolution(event("unresolved_walkaway"), "oncall_sms:acknowledged", "L"))
        self.assertIsNone(compose_resolution(event("unresolved_walkaway"), "dashboard:ongoing", "L"))
        self.assertIsNone(compose_resolution(event("unresolved_walkaway"), "dashboard:", "L"))

    def test_unknown_via_is_not_a_resolution(self):
        self.assertIsNone(compose_resolution(event("unresolved_walkaway"), "something_new"))


if __name__ == "__main__":
    unittest.main()
