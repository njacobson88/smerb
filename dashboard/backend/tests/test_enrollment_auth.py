"""Unit tests for enrollment-secret crypto (per-participant auth foundation)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrollment_auth import generate_enrollment_secret, hash_secret, verify_secret


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


if __name__ == "__main__":
    unittest.main()
