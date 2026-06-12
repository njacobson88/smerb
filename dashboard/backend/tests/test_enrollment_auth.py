"""Unit tests for enrollment-secret crypto (per-participant auth foundation)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrollment_auth import (
    generate_enrollment_secret, hash_secret, verify_secret,
    build_enrollment_url, enrollment_sms_text, enrollment_email_html,
)


class TestGenerate(unittest.TestCase):
    def test_high_entropy_and_unique(self):
        secrets_seen = {generate_enrollment_secret() for _ in range(1000)}
        self.assertEqual(len(secrets_seen), 1000)            # no collisions
        for s in list(secrets_seen)[:20]:
            self.assertGreaterEqual(len(s), 24)              # url-safe, ~32 chars

    def test_url_safe(self):
        for _ in range(50):
            s = generate_enrollment_secret()
            self.assertTrue(all(c.isalnum() or c in "-_" for c in s))


class TestHash(unittest.TestCase):
    def test_deterministic_hex(self):
        self.assertEqual(hash_secret("abc"), hash_secret("abc"))
        self.assertEqual(len(hash_secret("abc")), 64)        # sha256 hex
        self.assertNotEqual(hash_secret("abc"), hash_secret("abd"))

    def test_plaintext_not_recoverable(self):
        # The stored value must not equal the plaintext.
        s = generate_enrollment_secret()
        self.assertNotEqual(hash_secret(s), s)

    def test_handles_empty(self):
        self.assertEqual(len(hash_secret("")), 64)
        self.assertEqual(len(hash_secret(None)), 64)


class TestVerify(unittest.TestCase):
    def test_round_trip(self):
        s = generate_enrollment_secret()
        self.assertTrue(verify_secret(s, hash_secret(s)))

    def test_wrong_secret_rejected(self):
        s = generate_enrollment_secret()
        self.assertFalse(verify_secret("wrong", hash_secret(s)))

    def test_empty_matches_nothing(self):
        s = generate_enrollment_secret()
        self.assertFalse(verify_secret("", hash_secret(s)))
        self.assertFalse(verify_secret(s, ""))
        self.assertFalse(verify_secret(None, None))
        # An empty secret must NOT match the hash of empty string.
        self.assertFalse(verify_secret("", hash_secret("")))


class TestEnrollmentUrl(unittest.TestCase):
    def test_secret_in_fragment(self):
        url = build_enrollment_url("https://x.web.app", "493435788", "SECRET")
        # Secret must be after '#' (fragment) so it never reaches the server.
        self.assertEqual(url, "https://x.web.app/enroll#pid=493435788&s=SECRET")
        frag = url.split("#", 1)[1]
        self.assertIn("s=SECRET", frag)
        self.assertNotIn("SECRET", url.split("#", 1)[0])  # not in the server-sent part

    def test_trailing_slash_stripped(self):
        url = build_enrollment_url("https://x.web.app/", "1", "s")
        self.assertEqual(url, "https://x.web.app/enroll#pid=1&s=s")

    def test_messages_contain_url(self):
        url = build_enrollment_url("https://x.web.app", "1", "abc")
        self.assertIn(url, enrollment_sms_text(url))
        self.assertIn(url, enrollment_email_html(url))


if __name__ == "__main__":
    unittest.main()
