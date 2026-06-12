"""Unit tests for export-id validation (path-traversal guard on /api/exports/{id})."""
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export_utils import is_valid_export_id


class TestIsValidExportId(unittest.TestCase):
    def test_accepts_real_uuid4_hex(self):
        # This is exactly how main.py mints export_id / job_id.
        for _ in range(50):
            self.assertTrue(is_valid_export_id(uuid.uuid4().hex))

    def test_rejects_path_traversal(self):
        for bad in [
            "../../etc/passwd",
            "..%2f..%2fsecret",
            "/etc/shadow",
            "a/b/c",
            "....//....//x",
            "0123456789abcdef0123456789abcde/",   # slash at end
        ]:
            self.assertFalse(is_valid_export_id(bad), bad)

    def test_rejects_wrong_length(self):
        self.assertFalse(is_valid_export_id("abc123"))                 # too short
        self.assertFalse(is_valid_export_id("0" * 31))                 # 31
        self.assertFalse(is_valid_export_id("0" * 33))                 # 33

    def test_rejects_non_hex_chars(self):
        self.assertFalse(is_valid_export_id("g" * 32))                 # g not hex
        self.assertFalse(is_valid_export_id("0123456789abcdef0123456789abcde-"))  # dash

    def test_rejects_dotted_zip_trick(self):
        # would become "<id>..zip" / escape the .zip suffix
        self.assertFalse(is_valid_export_id("0123456789abcdef0123456789abcdef.zip"))
        self.assertFalse(is_valid_export_id("config.."))

    def test_rejects_non_strings(self):
        self.assertFalse(is_valid_export_id(None))
        self.assertFalse(is_valid_export_id(12345))
        self.assertFalse(is_valid_export_id(""))


if __name__ == "__main__":
    unittest.main()
