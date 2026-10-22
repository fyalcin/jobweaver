import os
import shutil
import tempfile
import unittest
from unittest import mock

import db

# Point db at a throwaway SQLite file BEFORE importing server (server runs
# db.init_db() at import time).
_TMP = tempfile.mkdtemp(prefix="gj-cv-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

import server  # noqa: E402
import user_assets  # noqa: E402


class CvEndpointsTest(unittest.TestCase):
    """GET/PUT /api/cv resolution + save-target behaviour.

    The repo-root CV-plaintext.txt is a user-agnostic placeholder template.
    Reads fall back to it for any user without a personal CV; EVERY save
    (default user included) writes profiles/<user>/CV-plaintext.txt and
    never touches the root template.

    Calls the endpoint functions directly with a fake session user; the
    user_assets BASE_DIR/PROFILES_DIR are patched into a temp directory so
    the real CV-plaintext.txt and profiles/ are never touched.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-cv-paths-")
        self.root_cv = os.path.join(self.tmp_dir, "CV-plaintext.txt")
        with open(self.root_cv, "w", encoding="utf-8") as f:
            f.write("ROOT CV")
        patcher = mock.patch.multiple(
            user_assets,
            BASE_DIR=self.tmp_dir,
            PROFILES_DIR=os.path.join(self.tmp_dir, "profiles"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _default_user():
        return {"id": 1, "username": db.DEFAULT_USER_USERNAME}

    @staticmethod
    def _wife():
        return {"id": 2, "username": "wife"}

    def _read(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    # --- GET ---------------------------------------------------------------
    def test_get_returns_base_template_for_user_without_personal_cv(self):
        for u in (self._default_user(), self._wife()):
            res = server.get_cv(user=u)
            self.assertEqual(res["content"], "ROOT CV")
            self.assertTrue(res["exists"])
            self.assertEqual(res["loaded_from"], "CV-plaintext.txt")

    def test_get_save_path_points_at_user_profile(self):
        res = server.get_cv(user=self._default_user())
        self.assertEqual(
            res["save_path"],
            os.path.join("profiles", db.DEFAULT_USER_USERNAME, "CV-plaintext.txt"),
        )

    def test_get_returns_personal_override_when_present(self):
        override = os.path.join(self.tmp_dir, "profiles", "wife")
        os.makedirs(override)
        with open(os.path.join(override, "CV-plaintext.txt"), "w", encoding="utf-8") as f:
            f.write("WIFE CV")
        res = server.get_cv(user=self._wife())
        self.assertEqual(res["content"], "WIFE CV")
        self.assertEqual(res["loaded_from"], os.path.join("profiles", "wife", "CV-plaintext.txt"))

    def test_get_falls_back_to_shared_when_no_file_exists(self):
        os.remove(self.root_cv)
        res = server.get_cv(user=self._wife())
        self.assertEqual(res["content"], "")
        self.assertFalse(res["exists"])

    # --- PUT ---------------------------------------------------------------
    def test_default_user_save_creates_profile_cv_and_leaves_base_intact(self):
        res = server.save_cv(server.CvTextPayload(content="UPDATED"), user=self._default_user())
        self.assertTrue(res["success"])
        his_cv = os.path.join(self.tmp_dir, "profiles", db.DEFAULT_USER_USERNAME, "CV-plaintext.txt")
        self.assertEqual(self._read(his_cv), "UPDATED")
        self.assertEqual(self._read(self.root_cv), "ROOT CV")
        self.assertEqual(
            res["save_path"],
            os.path.join("profiles", db.DEFAULT_USER_USERNAME, "CV-plaintext.txt"),
        )

    def test_other_user_save_creates_personal_override_and_leaves_root_intact(self):
        res = server.save_cv(server.CvTextPayload(content="WIFE EDITS"), user=self._wife())
        self.assertTrue(res["success"])
        her_file = os.path.join(self.tmp_dir, "profiles", "wife", "CV-plaintext.txt")
        self.assertEqual(self._read(her_file), "WIFE EDITS")
        self.assertEqual(self._read(self.root_cv), "ROOT CV")
        self.assertEqual(res["save_path"], os.path.join("profiles", "wife", "CV-plaintext.txt"))

    def test_other_user_with_override_edits_own_file(self):
        override_dir = os.path.join(self.tmp_dir, "profiles", "wife")
        os.makedirs(override_dir)
        her_file = os.path.join(override_dir, "CV-plaintext.txt")
        with open(her_file, "w", encoding="utf-8") as f:
            f.write("WIFE CV")
        server.save_cv(server.CvTextPayload(content="WIFE EDITS 2"), user=self._wife())
        self.assertEqual(self._read(her_file), "WIFE EDITS 2")
        self.assertEqual(self._read(self.root_cv), "ROOT CV")
        # Her edits are what she now gets back
        res = server.get_cv(user=self._wife())
        self.assertEqual(res["content"], "WIFE EDITS 2")

    def test_save_then_get_roundtrip_for_default_user(self):
        server.save_cv(server.CvTextPayload(content="ROUNDTRIP"), user=self._default_user())
        res = server.get_cv(user=self._default_user())
        self.assertEqual(res["content"], "ROUNDTRIP")


if __name__ == "__main__":
    unittest.main()
