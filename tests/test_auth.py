import os
import time
import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path

from jobweaver import auth
from jobweaver import db


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
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        previous = db.DB_PATH
        db.set_db_path(str(Path(temp.name, 'sessions.db')))
        self.addCleanup(db.set_db_path, previous)
        db.init_db()
        self.user_id = db.get_user_by_username('admin')['id']

    def test_roundtrip(self):
        token = auth.create_session_token(self.user_id)
        self.assertEqual(auth.verify_session_token(token), self.user_id)

    def test_tampered_token_fails(self):
        token = auth.create_session_token(self.user_id)
        forged = ('x' if token[0] != 'x' else 'y') + token[1:]
        self.assertIsNone(auth.verify_session_token(forged))

    def test_modified_user_id_fails(self):
        self.assertIsNone(auth.verify_session_token('43.9999999999.' + '0' * 64))

    def test_expired_token_fails(self):
        token = auth.create_session_token(self.user_id)
        with patch('jobweaver.auth.time.time', return_value=time.time() + auth.SESSION_TTL_SECONDS + 1):
            self.assertIsNone(auth.verify_session_token(token))

    def test_garbage_tokens_fail(self):
        self.assertIsNone(auth.verify_session_token(None))
        self.assertIsNone(auth.verify_session_token(""))
        self.assertIsNone(auth.verify_session_token("nonsense"))


if __name__ == "__main__":
    unittest.main()
