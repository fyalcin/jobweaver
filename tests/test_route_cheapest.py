import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from jobweaver import db
from jobweaver import user_assets

# Point db at a throwaway SQLite file BEFORE importing server (server runs
# db.init_db() at import time).
_TMP = tempfile.mkdtemp(prefix="gj-rc-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

from jobweaver import server  # noqa: E402
from jobweaver import generators  # noqa: E402


def setUpModule():
    # Discovery imports every module first; point at this module's DB while it runs.
    db.set_db_path(os.path.join(_TMP, "test.db"))


def tearDownModule():
    db.set_db_path(os.path.join(db.DATA_DIR, "jobweaver.db"))  # The runner's disposable default.


class ApplyRouteCheapestTest(unittest.TestCase):
    def test_appends_floor_when_enabled(self):
        self.assertEqual(generators.apply_route_cheapest("openai/gpt-5.6-luna", True), "openai/gpt-5.6-luna:floor")

    def test_disabled_leaves_model_untouched(self):
        self.assertEqual(generators.apply_route_cheapest("openai/gpt-5.6-luna", False), "openai/gpt-5.6-luna")

    def test_idempotent(self):
        self.assertEqual(generators.apply_route_cheapest("openai/gpt-5.6-luna:floor", True), "openai/gpt-5.6-luna:floor")

    def test_free_variants_skipped(self):
        self.assertEqual(generators.apply_route_cheapest("meta/llama-3.3-70b:free", True), "meta/llama-3.3-70b:free")

    def test_empty_model_passthrough(self):
        self.assertEqual(generators.apply_route_cheapest("", True), "")


class EffectiveAiModelRoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp_profiles = tempfile.mkdtemp(prefix="gj-rc-profiles-")
        self._orig_profiles_dir = user_assets.PROFILES_DIR
        user_assets.PROFILES_DIR = self.tmp_profiles
        self.username = "rcuser"

    def tearDown(self):
        user_assets.PROFILES_DIR = self._orig_profiles_dir
        shutil.rmtree(self.tmp_profiles, ignore_errors=True)

    def _write_user_config(self, cfg):
        user_dir = os.path.join(self.tmp_profiles, self.username)
        os.makedirs(user_dir, exist_ok=True)
        with open(os.path.join(user_dir, "scraper_config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def _user(self):
        return {"id": 999, "username": self.username}

    def test_flag_off_keeps_bare_model(self):
        self._write_user_config({"openrouter_model": "openai/gpt-5.6-luna", "route_cheapest": False})
        self.assertEqual(server._effective_ai_model(user=self._user(), purpose="scrape"), "openai/gpt-5.6-luna")

    def test_flag_on_appends_floor_to_configured_model(self):
        self._write_user_config({"openrouter_model": "anthropic/claude-sonnet-4.5", "route_cheapest": True})
        self.assertEqual(server._effective_ai_model(user=self._user(), purpose="scrape"),
                         "anthropic/claude-sonnet-4.5:floor")

    def test_flag_on_applies_to_explicit_model_choice(self):
        self._write_user_config({"route_cheapest": True})
        self.assertEqual(
            server._effective_ai_model("openai/gpt-5.6-luna", self._user()),
            "openai/gpt-5.6-luna:floor",
        )

    def test_default_off_without_config(self):
        self.assertEqual(server._effective_ai_model(user=self._user()), "z-ai/glm-5.3-flash")


class RouteCheapestConfigValidationTest(unittest.TestCase):
    def test_default_false(self):
        payload = server.ScraperConfigPayload.model_validate({})
        self.assertIs(payload.route_cheapest, False)

    def test_accepts_true(self):
        payload = server.ScraperConfigPayload.model_validate({"route_cheapest": True})
        self.assertIs(payload.route_cheapest, True)


if __name__ == "__main__":
    unittest.main()
