"""Unit tests for inbound-SMS classification (sms_utils)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sms_utils import (
    is_participant_error_reply,
    is_optout,
    is_resubscribe,
    parse_oncall_command,
    first_token_upper,
)


class TestFirstToken(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(first_token_upper("ack 493435788"), "ACK")
        self.assertEqual(first_token_upper("  safe  "), "SAFE")
        self.assertEqual(first_token_upper(""), "")
        self.assertEqual(first_token_upper(None), "")


class TestParticipantError(unittest.TestCase):
    def test_error_keywords(self):
        for b in ["ERROR", "error", "1", "ONE", "mistake", "Accident", "false", "ACCIDENTAL"]:
            self.assertTrue(is_participant_error_reply(b), b)

    def test_error_as_first_word(self):
        self.assertTrue(is_participant_error_reply("ERROR it was an accident"))
        self.assertTrue(is_participant_error_reply("1 sorry"))

    def test_freeform_is_not_error(self):
        for b in ["I am not okay", "help me", "2", "yes please call", "thanks"]:
            self.assertFalse(is_participant_error_reply(b), b)

    def test_empty(self):
        self.assertFalse(is_participant_error_reply(""))
        self.assertFalse(is_participant_error_reply(None))


class TestOptOut(unittest.TestCase):
    def test_optout_keywords(self):
        for b in ["STOP", "stop", "Unsubscribe", "CANCEL", "quit", "END", "REVOKE", "stopall"]:
            self.assertTrue(is_optout(b), b)

    def test_optout_first_word(self):
        self.assertTrue(is_optout("STOP texting me"))

    def test_not_optout(self):
        for b in ["ACK", "I am safe", "stopping by later is fine"]:
            # "stopping" != "STOP"
            self.assertFalse(is_optout(b), b)

    def test_resubscribe(self):
        self.assertTrue(is_resubscribe("START"))
        self.assertTrue(is_resubscribe("unstop"))
        self.assertFalse(is_resubscribe("STOP"))


class TestOncallCommand(unittest.TestCase):
    def test_known_commands(self):
        self.assertEqual(parse_oncall_command("ACK"), "acknowledged")
        self.assertEqual(parse_oncall_command("SAFE 493435788"), "contacted_safe")
        self.assertEqual(parse_oncall_command("988"), "escalated_988")
        self.assertEqual(parse_oncall_command("ongoing"), "ongoing")

    def test_unknown_command(self):
        self.assertIsNone(parse_oncall_command("hello"))
        self.assertIsNone(parse_oncall_command(""))
        self.assertIsNone(parse_oncall_command("ok thanks"))


if __name__ == "__main__":
    unittest.main()
