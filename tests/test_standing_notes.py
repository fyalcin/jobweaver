import os
import shutil
import tempfile
import unittest
from unittest import mock

import db

# Point db at a throwaway SQLite file before importing server
_TMP = tempfile.mkdtemp(prefix="gj-notes-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

import server  # noqa: E402
import user_assets  # noqa: E402
import generators  # noqa: E402


def setUpModule():
    # Discovery imports every module first; point at this module's DB while it runs.
    db.set_db_path(os.path.join(_TMP, "test.db"))


def tearDownModule():
    db.set_db_path(os.path.join(db.DATA_DIR, "jobweaver.db"))  # The runner's disposable default.


class StandingNotesTest(unittest.TestCase):
    """Test standing notes file resolution, effective CV composition,
    endpoints, and generator prompt grounding instructions.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-notes-paths-")
        self.root_cv = os.path.join(self.tmp_dir, "CV-plaintext.txt")
        with open(self.root_cv, "w", encoding="utf-8") as f:
            f.write("ROOT CV CONTENT")
        patcher = mock.patch.multiple(
            user_assets,
            BASE_DIR=self.tmp_dir,
            PROFILES_DIR=os.path.join(self.tmp_dir, "profiles"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    @staticmethod
    def _default_user():
        return {"id": 1, "username": db.DEFAULT_USER_USERNAME}

    @staticmethod
    def _user2():
        return {"id": 2, "username": "sam"}

    def test_load_standing_notes_empty_when_missing(self):
        self.assertEqual(user_assets.load_standing_notes(db.DEFAULT_USER_USERNAME), "")
        self.assertEqual(user_assets.load_standing_notes("sam"), "")

    def _write_cv(self, username, text):
        path = server._user_asset_save_path(username, "CV-plaintext.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_load_effective_cv_without_standing_notes(self):
        self.assertEqual(user_assets.load_effective_cv(db.DEFAULT_USER_USERNAME), "")  # never the root example
        self._write_cv(db.DEFAULT_USER_USERNAME, "USER CV CONTENT")
        self.assertEqual(user_assets.load_effective_cv(db.DEFAULT_USER_USERNAME), "USER CV CONTENT")

    def test_load_effective_cv_with_standing_notes(self):
        # Save standing notes for default user
        user_notes_path = server._user_asset_save_path(db.DEFAULT_USER_USERNAME, "standing_notes.txt")
        os.makedirs(os.path.dirname(user_notes_path), exist_ok=True)
        with open(user_notes_path, "w", encoding="utf-8") as f:
            f.write("- Working with Claude 3.7 Sonnet & Gemini 2.0 Flash\n- Agentic workflows")

        # Notes alone are not a CV.
        self.assertEqual(user_assets.load_effective_cv(db.DEFAULT_USER_USERNAME), "")
        self._write_cv(db.DEFAULT_USER_USERNAME, "USER CV CONTENT")
        effective = user_assets.load_effective_cv(db.DEFAULT_USER_USERNAME)
        self.assertIn("USER CV CONTENT", effective)
        self.assertIn("Recent Experience & Standing Notes:", effective)
        self.assertIn("Working with Claude 3.7 Sonnet & Gemini 2.0 Flash", effective)

        # Other user has no CV and does not see the root example or the notes
        self._write_cv("sam", "SAM CV")
        self.assertEqual(user_assets.load_effective_cv("sam"), "SAM CV")

    def test_get_and_put_profile_notes_endpoints(self):
        # 1. GET returns empty when no file
        res = server.get_profile_notes(user=self._default_user())
        self.assertEqual(res["notes"], "")
        self.assertFalse(res["exists"])

        # 2. PUT saves notes
        payload = server.ProfileNotesPayload(notes="- Proficient with LangGraph and local Ollama")
        put_res = server.save_profile_notes(body=payload, user=self._default_user())
        self.assertTrue(put_res["success"])

        # 3. GET returns saved notes
        res_after = server.get_profile_notes(user=self._default_user())
        self.assertEqual(res_after["notes"], "- Proficient with LangGraph and local Ollama")
        self.assertTrue(res_after["exists"])

        # 4. Ensure multi-user isolation: user2 has empty notes
        res_u2 = server.get_profile_notes(user=self._user2())
        self.assertEqual(res_u2["notes"], "")
        self.assertFalse(res_u2["exists"])


if __name__ == "__main__":
    unittest.main()
