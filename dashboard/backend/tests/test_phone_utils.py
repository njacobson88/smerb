"""Unit tests for phone normalization used in SMS participant matching."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phone_utils import normalize_phone, phones_match, to_e164


class TestNormalizePhone(unittest.TestCase):
    def test_strips_formatting(self):
        self.assertEqual(normalize_phone("(603) 555-1234"), "6035551234")
        self.assertEqual(normalize_phone("603-555-1234"), "6035551234")
        self.assertEqual(normalize_phone("603.555.1234"), "6035551234")
        self.assertEqual(normalize_phone("603 555 1234"), "6035551234")

    def test_strips_us_country_code(self):
        self.assertEqual(normalize_phone("+1 603 555 1234"), "6035551234")
        self.assertEqual(normalize_phone("16035551234"), "6035551234")
        self.assertEqual(normalize_phone("+16035551234"), "6035551234")

    def test_already_canonical(self):
        self.assertEqual(normalize_phone("6035551234"), "6035551234")

    def test_empty_and_none(self):
        self.assertEqual(normalize_phone(""), "")
        self.assertEqual(normalize_phone(None), "")
        self.assertEqual(normalize_phone("   "), "")

    def test_does_not_strip_leading_1_when_not_11_digits(self):
        # "1234567890" is a valid 10-digit number starting with 1 — keep as-is
        self.assertEqual(normalize_phone("1234567890"), "1234567890")


class TestPhonesMatch(unittest.TestCase):
    def test_equivalent_formats_match(self):
        self.assertTrue(phones_match("(603) 555-1234", "+16035551234"))
        self.assertTrue(phones_match("603-555-1234", "6035551234"))
        self.assertTrue(phones_match("1 603 555 1234", "603.555.1234"))

    def test_different_numbers_do_not_match(self):
        self.assertFalse(phones_match("6035551234", "6035559999"))

    def test_empty_matches_nothing(self):
        self.assertFalse(phones_match("", "6035551234"))
        self.assertFalse(phones_match(None, None))
        self.assertFalse(phones_match("6035551234", ""))


class TestToE164(unittest.TestCase):
    def test_formatted_us_number(self):
        # Yama's number, the case that surfaced this: must become +1XXXXXXXXXX.
        self.assertEqual(to_e164("(646) 413-0038"), "+16464130038")
        self.assertEqual(to_e164("646-413-0038"), "+16464130038")
        self.assertEqual(to_e164("314 397 9832"), "+13143979832")

    def test_already_e164_kept(self):
        self.assertEqual(to_e164("+16464130038"), "+16464130038")
        self.assertEqual(to_e164("+447911123456"), "+447911123456")  # non-US kept as-is

    def test_eleven_digit_with_leading_one(self):
        self.assertEqual(to_e164("16464130038"), "+16464130038")

    def test_empty_returns_blank(self):
        self.assertEqual(to_e164(""), "")
        self.assertEqual(to_e164(None), "")
        self.assertEqual(to_e164("   "), "")
        self.assertEqual(to_e164("no digits here"), "")


if __name__ == "__main__":
    unittest.main()
