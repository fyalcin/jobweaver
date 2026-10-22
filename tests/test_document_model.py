"""document_model is a separate setting from the scoring model.

Context: `openrouter_model` prices the per-posting scoring of the daily scrape (~50 calls/day)
as well as document generation (~2 calls per application). Raising it to improve letters is
therefore a ~25x volume mistake. These tests pin the split so it cannot silently re-merge.
"""
import json
import os
import shutil
import tempfile
import unittest
import unittest.mock

import db
import user_assets

# Point db at a throwaway SQLite file BEFORE importing server (server runs db.init_db() at import).
_TMP = tempfile.mkdtemp(prefix="gj-dm-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

import server  # noqa: E402
import generators  # noqa: E402


class ResolveDocumentModelTest(unittest.TestCase):
    def test_defaults_to_the_cheap_model_when_unset(self):
        self.assertEqual(generators.resolve_document_model({}), "z-ai/glm-5.3-flash")
        self.assertEqual(generators.resolve_document_model(None), "z-ai/glm-5.3-flash")

    def test_blank_value_falls_back_to_default(self):
        self.assertEqual(generators.resolve_document_model({"document_model": "   "}), "z-ai/glm-5.3-flash")

    def test_user_value_wins(self):
        self.assertEqual(generators.resolve_document_model({"document_model": "anthropic/claude-sonnet-5"}),
                         "anthropic/claude-sonnet-5")

    def test_route_cheapest_applies_to_it(self):
        cfg = {"document_model": "anthropic/claude-sonnet-5", "route_cheapest": True}
        self.assertEqual(generators.resolve_document_model(cfg), "anthropic/claude-sonnet-5:floor")

    def test_scrape_model_is_unaffected_by_document_model(self):
        cfg = {"openrouter_model": "z-ai/glm-5.3-flash", "document_model": "anthropic/claude-sonnet-5"}
        self.assertEqual(generators.resolve_scrape_model(cfg), "z-ai/glm-5.3-flash")
        self.assertEqual(generators.resolve_document_model(cfg), "anthropic/claude-sonnet-5")

    def test_scrape_model_default_when_unset(self):
        self.assertEqual(generators.resolve_scrape_model({}), "z-ai/glm-5.3-flash")


class EffectiveModelPurposeTest(unittest.TestCase):
    def setUp(self):
        self.tmp_profiles = tempfile.mkdtemp(prefix="gj-dm-profiles-")
        self._orig_profiles_dir = user_assets.PROFILES_DIR
        user_assets.PROFILES_DIR = self.tmp_profiles
        self.username = "dmuser"

    def tearDown(self):
        user_assets.PROFILES_DIR = self._orig_profiles_dir
        shutil.rmtree(self.tmp_profiles, ignore_errors=True)

    def _write_user_config(self, cfg):
        user_dir = os.path.join(self.tmp_profiles, self.username)
        os.makedirs(user_dir, exist_ok=True)
        with open(os.path.join(user_dir, "scraper_config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def _user(self):
        return {"id": 998, "username": self.username}

    def test_document_purpose_uses_document_model(self):
        self._write_user_config({"openrouter_model": "z-ai/glm-5.3-flash",
                                 "document_model": "anthropic/claude-sonnet-5"})
        self.assertEqual(server._effective_ai_model(user=self._user()), "anthropic/claude-sonnet-5")
        self.assertEqual(server._effective_ai_model(user=self._user(), purpose="document"),
                         "anthropic/claude-sonnet-5")

    def test_scrape_purpose_uses_openrouter_model(self):
        self._write_user_config({"openrouter_model": "z-ai/glm-5.3-flash",
                                 "document_model": "anthropic/claude-sonnet-5"})
        self.assertEqual(server._effective_ai_model(user=self._user(), purpose="scrape"),
                         "z-ai/glm-5.3-flash")

    def test_document_purpose_defaults_when_key_absent(self):
        self._write_user_config({"openrouter_model": "openai/gpt-5.6-luna"})
        self.assertEqual(server._effective_ai_model(user=self._user()), "z-ai/glm-5.3-flash")

    def test_explicit_request_model_still_wins(self):
        self._write_user_config({"document_model": "z-ai/glm-5.3-flash"})
        self.assertEqual(server._effective_ai_model("openai/gpt-5.6-luna", self._user()),
                         "openai/gpt-5.6-luna")

    def test_document_requests_without_a_model_use_the_document_model(self):
        # The web UI used to send the scoring model with every generate/refine request, and the request
        # classes defaulted to a hard-coded model, so the Documents Model setting never applied.
        self._write_user_config({"openrouter_model": "z-ai/glm-5.3-flash",
                                 "document_model": "anthropic/claude-sonnet-5"})
        requests = [server.GenerateRequest(job_id="j"), server.RefineStartRequest(job_id="j", doc_type="cv"),
                    server.RefineIterateRequest(job_id="j", document_type="letter", current_tex="", feedback="f")]
        for req in requests:
            self.assertIsNone(req.modelName, type(req).__name__)
            self.assertEqual(server._effective_ai_model(req.modelName, self._user()), "anthropic/claude-sonnet-5")

    def test_frontend_document_requests_do_not_send_the_scoring_model(self):
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp", "src", "hooks")
        for name in ("useJobs.js", "useBatchGen.js", "useDailyTab.js", "useRefine.js", "useStudio.js"):
            with open(os.path.join(root, name), encoding="utf-8") as f:
                self.assertNotIn("aiModel", f.read(), name)

    def test_missing_config_file_is_not_an_error(self):
        self.assertEqual(server._effective_ai_model(user=self._user()), "z-ai/glm-5.3-flash")


class ConfigPayloadTest(unittest.TestCase):
    def test_document_model_field_round_trips(self):
        payload = server.ScraperConfigPayload.model_validate({"document_model": "anthropic/claude-sonnet-5"})
        self.assertEqual(payload.document_model, "anthropic/claude-sonnet-5")

    def test_document_model_defaults_to_empty(self):
        self.assertEqual(server.ScraperConfigPayload.model_validate({}).document_model, "")


if __name__ == "__main__":
    unittest.main()


class DownloadNameTest(unittest.TestCase):
    def test_saved_pdfs_carry_the_applicant_name_not_the_company(self):
        with unittest.mock.patch.object(server, "load_cv_text", return_value="Alex Muster, MSc\nPython"):
            self.assertEqual(server._download_name("u", "CV-Körber.pdf"), "Alex_Muster_CV.pdf")
            self.assertEqual(server._download_name("u", "Letter-Körber.pdf"), "Alex_Muster_Cover_Letter.pdf")
            self.assertEqual(server._download_name("u", "notes.pdf"), "notes.pdf")

