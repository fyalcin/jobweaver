import os
import json
import shutil
import tempfile
import unittest
from unittest import mock

import db

# Point db at a throwaway SQLite file BEFORE importing server (server runs
# db.init_db() at import time).
_TMP = tempfile.mkdtemp(prefix="gj-cfg-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

import server  # noqa: E402
import user_assets  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class ConfigEndpointsTest(unittest.TestCase):
    """GET/PUT /api/config per-user resolution + save-target behaviour.

    The repo-root scraper_config.json is a user-agnostic base template.
    Reads fall back to it for any user without a personal config; EVERY
    save (default user included) writes profiles/<user>/scraper_config.json
    and never touches the base template.

    Regression history: saving as a user without a personal config used to
    overwrite the shared root file; later the default user's root file was
    treated as their personal master — both superseded by the base-template
    layout.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-cfg-paths-")
        self.root_cfg = os.path.join(self.tmp_dir, "scraper_config.json")
        with open(self.root_cfg, "w", encoding="utf-8") as f:
            json.dump({"linkedin": {"keywords": "ROOT KW"}}, f)
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

    def _read_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # --- GET ---------------------------------------------------------------
    def test_get_returns_base_config_for_user_without_override(self):
        for u in (self._default_user(), self._wife()):
            res = server.get_config(user=u)
            self.assertEqual(res["linkedin"]["keywords"], "ROOT KW")

    def test_get_resolves_personal_override_when_present(self):
        override_dir = os.path.join(self.tmp_dir, "profiles", "wife")
        os.makedirs(override_dir)
        with open(os.path.join(override_dir, "scraper_config.json"), "w", encoding="utf-8") as f:
            json.dump({"linkedin": {"keywords": "WIFE KW"}}, f)
        res = server.get_config(user=self._wife())
        self.assertEqual(res["linkedin"]["keywords"], "WIFE KW")

    def test_get_404_when_no_config_exists_anywhere(self):
        os.remove(self.root_cfg)
        with self.assertRaises(HTTPException) as ctx:
            server.get_config(user=self._wife())
        self.assertEqual(ctx.exception.status_code, 404)

    # --- PUT ---------------------------------------------------------------
    def test_default_user_save_creates_profile_config_and_leaves_base_intact(self):
        server.save_config({"linkedin": {"keywords": "ADMIN KW"}}, user=self._default_user())
        his_cfg = os.path.join(self.tmp_dir, "profiles", db.DEFAULT_USER_USERNAME, "scraper_config.json")
        self.assertEqual(self._read_json(his_cfg)["linkedin"]["keywords"], "ADMIN KW")
        self.assertEqual(self._read_json(self.root_cfg)["linkedin"]["keywords"], "ROOT KW")

    def test_other_user_save_creates_override_and_leaves_base_intact(self):
        server.save_config({"linkedin": {"keywords": "WIFE KW"}}, user=self._wife())
        her_cfg = os.path.join(self.tmp_dir, "profiles", "wife", "scraper_config.json")
        self.assertEqual(self._read_json(her_cfg)["linkedin"]["keywords"], "WIFE KW")
        self.assertEqual(self._read_json(self.root_cfg)["linkedin"]["keywords"], "ROOT KW")

    def test_other_user_with_override_edits_own_file(self):
        override_dir = os.path.join(self.tmp_dir, "profiles", "wife")
        os.makedirs(override_dir)
        her_cfg = os.path.join(override_dir, "scraper_config.json")
        with open(her_cfg, "w", encoding="utf-8") as f:
            json.dump({"linkedin": {"keywords": "WIFE KW"}}, f)
        server.save_config({"linkedin": {"keywords": "WIFE KW 2"}}, user=self._wife())
        self.assertEqual(self._read_json(her_cfg)["linkedin"]["keywords"], "WIFE KW 2")
        self.assertEqual(self._read_json(self.root_cfg)["linkedin"]["keywords"], "ROOT KW")

    def test_generation_preferences_survive_unrelated_save(self):
        settings = {"document_engine": "latex", "typst_cv_template": "base-cv.typ", "compact_cv": True}
        server.save_config({"auto_generate": settings}, user=self._wife())
        server.save_config({"document_model": "chosen-model"}, user=self._wife())
        saved = server.get_config(user=self._wife())["auto_generate"]
        for key, value in settings.items():
            self.assertEqual(saved[key], value)

    def test_bad_engine_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            server.save_config({"auto_generate": {"document_engine": "unknown"}}, user=self._wife())
        self.assertEqual(error.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()

class ReviewedBaselineSettingsTest(unittest.TestCase):
    def test_first_default_and_explicit_engine_choice_are_distinct(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp, mock.patch.multiple(
                user_assets, BASE_DIR=temp, PROFILES_DIR=str(Path(temp, 'profiles'))):
            user = {'id': 1, 'username': 'synthetic'}
            profile = Path(user_assets.user_profile_dir('synthetic'))
            (profile / 'approved').mkdir(parents=True)
            (profile / 'approved' / 'cv.tex').write_text('reviewed synthetic baseline')
            config = profile / 'scraper_config.json'
            config.write_text(json.dumps({'auto_generate': {'document_engine': 'typst', 'compact_cv': True, 'extension': 'keep'}}))
            self.assertEqual(server.get_config(user=user)['auto_generate']['document_engine'], 'latex')
            self.assertEqual(json.loads(config.read_text())['auto_generate']['document_engine'], 'typst')
            server.save_config({'auto_generate': {'document_engine': 'typst'}}, user=user)
            self.assertEqual(server.load_document_engine_config(user)[0], 'typst')
            saved = json.loads(config.read_text())['auto_generate']
            self.assertTrue(saved['compact_cv'])
            self.assertEqual(saved['extension'], 'keep')
            self.assertNotIn('reviewed_baseline', saved)
