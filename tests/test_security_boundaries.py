"""Security behavior through the normal authenticated HTTP interface.

Run only through scripts/test_isolated.py; every test uses fictional temporary data.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from jobweaver import auth
from jobweaver import db
from jobweaver import server
from jobweaver import user_assets


class SecurityBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.patch = patch.multiple(user_assets, BASE_DIR=str(root), PROFILES_DIR=str(root / 'profiles'))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        original = db.DB_PATH
        db.set_db_path(str(root / 'jobs.db'))
        self.addCleanup(db.set_db_path, original)
        db.init_db()
        self.alice = db.create_user('alice', auth.hash_password('fictional-alice-password'))
        self.bob = db.create_user('bob', auth.hash_password('fictional-bob-password'))
        user_assets.ensure_user_dirs('alice')
        user_assets.ensure_user_dirs('bob')
        self.client = TestClient(server.app, base_url='http://127.0.0.1')
        self.addCleanup(self.client.close)
        response = self.client.post('/api/auth/login', json={
            'username': 'alice', 'password': 'fictional-alice-password'})
        self.assertEqual(response.status_code, 200)

    def test_template_cannot_read_another_users_cv(self):
        secret = Path(user_assets.user_profile_dir('bob'), 'CV-plaintext.txt')
        secret.write_text('BOB_ONLY_FICTIONAL_SENTINEL')
        response = self.client.post('/api/documents', json={
            'title': 'Untrusted template', 'engine': 'typst', 'template_source': str(secret)})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('BOB_ONLY_FICTIONAL_SENTINEL', response.text)
        self.assertEqual(self.client.get('/api/documents').json()['documents'], [])

    def test_download_cannot_follow_a_link_into_another_profile(self):
        secret = Path(user_assets.user_profile_dir('bob'), 'CV-plaintext.txt')
        secret.write_text('BOB_ONLY_FICTIONAL_SENTINEL')
        Path(user_assets.user_drafts_dir('alice'), 'exposed.tex').symlink_to(secret)
        response = self.client.get('/api/download/draft/exposed.tex')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('BOB_ONLY_FICTIONAL_SENTINEL', response.text)

    def test_only_advertised_templates_can_be_used(self):
        folder = Path(user_assets.BASE_DIR, 'base-typst')
        folder.mkdir()
        (folder / 'base-cv.typ').write_text('= Fictional root template')
        for template in ('../outside.txt', '/etc/passwd', 'CV-plaintext.txt'):
            with self.subTest(template=template):
                response = self.client.post('/api/documents', json={
                    'title': 'Invalid', 'template_source': template})
                self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/documents', json={
            'title': 'Valid', 'template_source': 'base-typst/base-cv.typ'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['content'], '= Fictional root template')

    def test_cross_origin_api_reads_and_writes_are_rejected(self):
        for method, path, payload in (('GET', '/api/cv', None),
                                      ('PUT', '/api/profile/notes', {'notes': 'unwanted edit'})):
            with self.subTest(method=method):
                response = self.client.request(method, path, json=payload,
                                               headers={'Origin': 'http://127.0.0.1:8999'})
                self.assertEqual(response.status_code, 403)
        response = self.client.put('/api/profile/notes', json={'notes': 'owned edit'},
                                   headers={'Origin': 'http://127.0.0.1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/profile/notes').json()['notes'], 'owned edit')
        # Vite preserves the browser-facing Host, including its port.
        response = self.client.put('/api/profile/notes', json={'notes': 'development proxy'},
                                  headers={'Host': 'localhost:5173', 'Origin': 'http://localhost:5173'})
        self.assertEqual(response.status_code, 200)

    def test_foreign_host_and_cross_site_navigation_are_rejected(self):
        self.assertEqual(self.client.get('/api/auth/me', headers={'Host': 'attacker.invalid'}).status_code, 400)
        self.assertEqual(self.client.get('/api/cv', headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)

    def test_logout_revokes_a_copied_cookie_without_revoking_another_login(self):
        copied = self.client.cookies.get(auth.SESSION_COOKIE_NAME)
        second = TestClient(server.app, base_url='http://127.0.0.1')
        self.addCleanup(second.close)
        second.post('/api/auth/login', json={'username': 'alice', 'password': 'fictional-alice-password'})
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.client.cookies.set(auth.SESSION_COOKIE_NAME, copied)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(second.get('/api/auth/me').status_code, 200)

    def test_password_change_revokes_existing_sessions(self):
        from jobweaver import manage_users
        from types import SimpleNamespace
        with patch('getpass.getpass', return_value='fictional-new-password'):
            self.assertEqual(manage_users.cmd_passwd(SimpleNamespace(username='alice')), 0)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        response = self.client.post('/api/auth/login', json={
            'username': 'alice', 'password': 'fictional-new-password'})
        self.assertEqual(response.status_code, 200)

    def test_deleted_user_files_cannot_be_inherited_by_a_new_user(self):
        from jobweaver import manage_users
        from types import SimpleNamespace
        secret = Path(user_assets.user_profile_dir('bob'), 'CV-plaintext.txt')
        secret.write_text('BOB_ONLY_FICTIONAL_SENTINEL')
        with patch('builtins.input', return_value='yes'):
            self.assertEqual(manage_users.cmd_remove(SimpleNamespace(username='bob')), 0)
        with patch('getpass.getpass', return_value='fictional-replacement-password'):
            self.assertEqual(manage_users.cmd_add(SimpleNamespace(username='bob', display_name=None)), 1)
        self.assertTrue(secret.exists())  # Retention is explicit; this fix does not delete files.

    def test_new_user_cannot_adopt_orphaned_profile_files(self):
        folder = Path(user_assets.PROFILES_DIR, 'orphan')
        folder.mkdir()
        (folder / 'CV-plaintext.txt').write_text('ORPHAN_ONLY_FICTIONAL_SENTINEL')
        with self.assertRaises(ValueError):
            db.create_user('orphan', auth.hash_password('fictional-password'))

    def test_username_cannot_escape_the_profiles_directory(self):
        for name in ('../outside', '/tmp/outside', '.', 'x/y'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                db.create_user(name, 'unused')

    def test_repeated_sign_in_attempts_are_limited_and_recover(self):
        for _ in range(5):
            response = self.client.post('/api/auth/login', json={'username': 'unknown', 'password': 'wrong'})
            self.assertEqual(response.status_code, 401)
        response = self.client.post('/api/auth/login', json={'username': 'unknown', 'password': 'wrong'})
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers['retry-after']), 0)
        import time
        with patch('jobweaver.server.time.time', return_value=time.time() + 61):
            response = self.client.post('/api/auth/login', json={'username': 'unknown', 'password': 'wrong'})
        self.assertEqual(response.status_code, 401)

    def test_password_reset_during_sign_in_cannot_create_an_old_password_session(self):
        verify = auth.verify_password
        replacement = auth.hash_password('fictional-replacement-password')
        def reset_after_verification(password, stored):
            valid = verify(password, stored)
            db.update_user_fields(self.alice['id'], password_hash=replacement)
            return valid
        with patch('jobweaver.auth.verify_password', side_effect=reset_after_verification):
            response = self.client.post('/api/auth/login', json={
                'username': 'alice', 'password': 'fictional-alice-password'})
        self.assertEqual(response.status_code, 401)

    def test_bootstrap_does_not_resurrect_a_retired_username(self):
        for user in db.list_users():
            db.delete_user(user['id'])
        db.init_db()
        self.assertIsNone(db.get_user_by_username('admin'))
        self.assertIsNone(db.get_user_by_username('alice'))
        self.assertIsNone(db.get_user_by_username('bob'))

    def test_legacy_password_is_upgraded_at_login(self):
        import hashlib
        salt = '0123456789abcdef0123456789abcdef'
        legacy = 'pbkdf2_sha256$200000$' + salt + '$' + hashlib.pbkdf2_hmac(
            'sha256', b'fictional-alice-password', salt.encode(), 200_000).hex()
        db.update_user_fields(self.alice['id'], password_hash=legacy)
        response = self.client.post('/api/auth/login', json={
            'username': 'alice', 'password': 'fictional-alice-password'})
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(int(db.get_user_by_username('alice')['password_hash'].split('$')[1]), 600_000)

    def test_https_deployment_requires_https_and_marks_the_cookie_secure(self):
        import os
        with patch.dict(os.environ, {'JOBWEAVER_ALLOWED_HOSTS': 'jobs.example.test', 'JOBWEAVER_HTTPS_ONLY': '1'}):
            self.assertEqual(self.client.get('/api/demo').status_code, 400)
            secure = TestClient(server.app, base_url='https://jobs.example.test')
            self.addCleanup(secure.close)
            response = secure.post('/api/auth/login', json={'username': 'bob', 'password': 'fictional-bob-password'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('Secure', response.headers['set-cookie'])
            self.assertEqual(secure.get('/api/auth/me').status_code, 200)
