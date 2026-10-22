import os
import time
import unittest

import auth


class TestPasswordHashing(unittest.TestCase):
    def test_hash_and_verify_roundtrip(self):
        stored = auth.hash_password("s3cret-password")
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertTrue(auth.verify_password("s3cret-password", stored))

    def test_wrong_password_fails(self):
        stored = auth.hash_password("s3cret-password")
        self.assertFalse(auth.verify_password("wrong", stored))

    def test_empty_or_none_stored_hash_fails(self):
        self.assertFalse(auth.verify_password("x", None))
        self.assertFalse(auth.verify_password("x", ""))

    def test_passwords_are_salted(self):
        a = auth.hash_password("same")
        b = auth.hash_password("same")
        self.assertNotEqual(a, b)

    def test_malformed_hash_fails_safely(self):
        self.assertFalse(auth.verify_password("x", "not-a-valid-hash"))
        self.assertFalse(auth.verify_password("x", "pbkdf2_sha256$abc$de$ff"))


class TestSessionTokens(unittest.TestCase):
    def test_roundtrip(self):
        token = auth.create_session_token(42)
        self.assertEqual(auth.verify_session_token(token), 42)

    def test_tampered_token_fails(self):
        token = auth.create_session_token(42)
        user_id, expires, sig = token.split(".")
        forged_sig = ("0" * len(sig)) if set(sig) != {"0"} else ("1" * len(sig))
        self.assertIsNone(auth.verify_session_token(f"{user_id}.{expires}.{forged_sig}"))

    def test_modified_user_id_fails(self):
        token = auth.create_session_token(42)
        _, expires, sig = token.split(".")
        # Signature no longer matches the altered payload
        self.assertIsNone(auth.verify_session_token(f"43.{expires}.{sig}"))

    def test_expired_token_fails(self):
        expires = int(time.time()) - 10
        import hmac
        import hashlib
        payload = f"7.{expires}"
        sig = hmac.new(auth._load_secret(), payload.encode(), hashlib.sha256).hexdigest()
        self.assertIsNone(auth.verify_session_token(f"{payload}.{sig}"))

    def test_garbage_tokens_fail(self):
        self.assertIsNone(auth.verify_session_token(None))
        self.assertIsNone(auth.verify_session_token(""))
        self.assertIsNone(auth.verify_session_token("nonsense"))


if __name__ == "__main__":
    unittest.main()
