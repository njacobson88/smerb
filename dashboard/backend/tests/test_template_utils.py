"""Unit tests for safe_format — the compliance-template substitution that
replaces unsafe str.format(**vars) (format-string injection guard)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from template_utils import safe_format

VARS = {"name": "Alex", "participant_id": "493435788", "compliance_pct": 87.5, "days": 3}


class TestSafeFormatLegit(unittest.TestCase):
    def test_simple_substitution(self):
        self.assertEqual(safe_format("Hi {name}!", VARS), "Hi Alex!")

    def test_multiple_fields(self):
        self.assertEqual(
            safe_format("{name} ({participant_id})", VARS), "Alex (493435788)")

    def test_format_spec_allowed(self):
        self.assertEqual(safe_format("{compliance_pct:.0f}%", VARS), "88%")

    def test_no_placeholders(self):
        self.assertEqual(safe_format("Just text.", VARS), "Just text.")

    def test_non_string_passthrough(self):
        self.assertIsNone(safe_format(None, VARS))


class TestSafeFormatBlocksInjection(unittest.TestCase):
    def test_blocks_attribute_access(self):
        # The actual exploit shape against str.format.
        with self.assertRaises(ValueError):
            safe_format("{name.__class__.__init__.__globals__}", VARS)

    def test_blocks_index_access(self):
        with self.assertRaises(ValueError):
            safe_format("{name[0]}", VARS)

    def test_blocks_positional(self):
        with self.assertRaises(ValueError):
            safe_format("{0}", VARS)
        with self.assertRaises(ValueError):
            safe_format("{}", VARS)

    def test_blocks_nested_format_spec(self):
        with self.assertRaises(ValueError):
            safe_format("{compliance_pct:{name}}", VARS)

    def test_unknown_field_raises_not_leaks(self):
        with self.assertRaises(ValueError):
            safe_format("{secret_key}", VARS)

    def test_str_format_would_have_leaked(self):
        # Sanity: prove the old path was actually exploitable, so this guard matters.
        leaked = "{name.__class__}".format(**VARS)
        self.assertIn("str", leaked)  # str.format happily walks the attribute


if __name__ == "__main__":
    unittest.main()
