import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import db
import user_assets

# Point db at a throwaway SQLite file BEFORE importing server (server runs
# db.init_db() at import time).
_TMP = tempfile.mkdtemp(prefix="gj-dn-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

import server  # noqa: E402
import scrapers  # noqa: E402
import generators  # noqa: E402


_NOISY_DESCRIPTION = (
    "Sprache auswählen\n"
    "German\nEnglish\n"
    "Cookie consent notice here\n"
    "Wir verwenden cookies zur Verbesserung.\n"
    "Senior Backend Developer\n"
    "We are looking for an experienced Python developer to join our platform team in Vienna. "
    "You will design and operate scalable services, collaborate with product teams, and help us "
    "build reliable data pipelines. Our stack includes Python, PostgreSQL, Docker and Kubernetes. "
    "We offer flexible working hours, hybrid setups and a strong engineering culture.\n"
)
_CLEAN_MARKER = "Senior Backend Developer"
_NOISE_MARKER = "Cookie consent notice"


def _stub_ai_payload(description):
    return {
        "german_level": "none",
        "requires_german": False,
        "salary": "Not Specified",
        "skills": "Python",
        "summary": "A stub summary.",
        "company_contact": None,
        "match_score": 42,
        "description": description,
    }


def _stub_json_response(**overrides):
    payload = {
        "german_level": "none",
        "minimum_salary": "Not Specified",
        "skills": "Python",
        "summary": "A stub summary.",
        "company_contact": None,
    }
    payload.update(overrides)
    return json.dumps(payload)


class ResolveSourceBucketTest(unittest.TestCase):
    def test_scraper_params_map_to_platform_buckets(self):
        cases = {
            "linkedin": "linkedin",
            "linkedin-apify": "linkedin",
            "karriere": "karriere",
            "karriere-apify": "karriere",
            "manual": "manual",
        }
        for source, bucket in cases.items():
            self.assertEqual(scrapers.resolve_source_bucket(source), bucket)

    def test_stored_job_labels_map_to_platform_buckets(self):
        self.assertEqual(scrapers.resolve_source_bucket("LinkedIn (Apify)"), "linkedin")
        self.assertEqual(scrapers.resolve_source_bucket("Karriere (Apify)"), "karriere")
        self.assertEqual(scrapers.resolve_source_bucket("Company feed (Greenhouse)"), "company_feeds")

    def test_unknown_source_returns_none(self):
        self.assertIsNone(scrapers.resolve_source_bucket("Some Legacy Label"))
        self.assertIsNone(scrapers.resolve_source_bucket(""))
        self.assertIsNone(scrapers.resolve_source_bucket(None))


class DenoiseEnabledTest(unittest.TestCase):
    def setUp(self):
        self.tmp_profiles = tempfile.mkdtemp(prefix="gj-dn-profiles-")
        self._orig_profiles_dir = user_assets.PROFILES_DIR
        user_assets.PROFILES_DIR = self.tmp_profiles
        self.username = "denoiseuser"

    def tearDown(self):
        user_assets.PROFILES_DIR = self._orig_profiles_dir
        shutil.rmtree(self.tmp_profiles, ignore_errors=True)

    def _write_user_config(self, cfg):
        user_dir = os.path.join(self.tmp_profiles, self.username)
        os.makedirs(user_dir, exist_ok=True)
        with open(os.path.join(user_dir, "scraper_config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def test_default_is_manual_only_when_key_missing(self):
        self._write_user_config({"linkedin": {"keywords": "x"}})
        self.assertTrue(scrapers.denoise_enabled(self.username, "manual"))
        self.assertFalse(scrapers.denoise_enabled(self.username, "linkedin-apify"))
        self.assertFalse(scrapers.denoise_enabled(self.username, "karriere-apify"))

    def test_config_selection_is_honoured(self):
        self._write_user_config({"denoise_sources": ["manual", "karriere"]})
        self.assertTrue(scrapers.denoise_enabled(self.username, "Karriere (Apify)"))
        self.assertFalse(scrapers.denoise_enabled(self.username, "LinkedIn (Apify)"))

    def test_malformed_config_falls_back_to_default(self):
        self._write_user_config({"denoise_sources": "linkedin"})
        self.assertTrue(scrapers.denoise_enabled(self.username, "manual"))
        self.assertFalse(scrapers.denoise_enabled(self.username, "linkedin"))

    def test_unknown_source_defaults_to_denoise_on(self):
        self._write_user_config({"denoise_sources": []})
        self.assertTrue(scrapers.denoise_enabled(self.username, "Some Legacy Label"))


class ProcessJobDenoiseFlagTest(unittest.TestCase):
    def setUp(self):
        self.captured = []
        patcher = mock.patch.object(
            scrapers, "run_ai_prompt",
            side_effect=lambda prompt, **kw: (self.captured.append(prompt), _stub_json_response())[1],
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_denoise_true_cleans_description_and_requests_echo(self):
        result = scrapers.process_job_with_ai(_NOISY_DESCRIPTION, denoise=True)
        self.assertNotIn(_NOISE_MARKER, result["description"])
        self.assertIn(_CLEAN_MARKER, result["description"])
        self.assertIn("cleaned_description", self.captured[0])

    def test_denoise_false_keeps_description_and_skips_echo(self):
        result = scrapers.process_job_with_ai(_NOISY_DESCRIPTION, denoise=False)
        self.assertIn(_NOISE_MARKER, result["description"])
        self.assertNotIn("cleaned_description", self.captured[0])

    def test_denoise_true_falls_back_without_echo_when_filter_aborts(self):
        calls = []

        def flaky_run_ai_prompt(prompt, **kwargs):
            calls.append(prompt)
            if "cleaned_description" in prompt:
                raise generators.AIContentFilterError("content filter")
            return _stub_json_response()

        with mock.patch.object(scrapers, "run_ai_prompt", side_effect=flaky_run_ai_prompt):
            result = scrapers.process_job_with_ai(_NOISY_DESCRIPTION, denoise=True)
        self.assertEqual(len(calls), 2)
        self.assertNotIn(_NOISE_MARKER, result["description"])


class ReprocessDenoiseGatingTest(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.user = db.create_user(f"dnuser_{id(self)}", password_hash="x", display_name="DN")

    def tearDown(self):
        db.delete_user(self.user["id"])

    def _add_job(self, job_id, source):
        db.upsert_job(
            {
                "id": job_id,
                "job_url": f"https://example.com/job/{job_id}",
                "title": "Developer",
                "company": "Example GmbH",
                "date_scraped": "2026-09-01",
                "source": source,
                "status": "new",
                "processed": 0,
                "description": _NOISY_DESCRIPTION,
            },
            user_id=self.user["id"],
        )

    def _run_reprocess(self, job_id):
        task_id = f"dn-task-{job_id}"
        db.async_task_create(task_id, "reprocess", total=1, user_id=self.user["id"])
        captured = {}

        def fake_ai(description, cv_text=None, model_name=None, denoise=True):
            captured["denoise"] = denoise
            return _stub_ai_payload(description)

        with mock.patch.object(server._scrapers, "process_job_with_ai", side_effect=fake_ai):
            server._run_reprocess_bg(task_id, {"id": self.user["id"], "username": self.user["username"]})
        return captured

    def test_scraped_source_denoise_off_by_default(self):
        self._add_job("li_dn_1", "LinkedIn (Apify)")
        captured = self._run_reprocess("li_dn_1")
        self.assertFalse(captured["denoise"])

    def test_manual_source_denoise_on_by_default(self):
        self._add_job("manual_dn_1", "manual")
        captured = self._run_reprocess("manual_dn_1")
        self.assertTrue(captured["denoise"])


class DenoiseConfigValidationTest(unittest.TestCase):
    def test_unknown_and_case_variation_normalised(self):
        payload = server.ScraperConfigPayload.model_validate({"denoise_sources": ["LinkedIn", "bogus", "MANUAL"]})
        self.assertEqual(payload.denoise_sources, ["linkedin", "manual"])

    def test_default_is_manual_only(self):
        payload = server.ScraperConfigPayload.model_validate({})
        self.assertEqual(payload.denoise_sources, ["manual"])


if __name__ == "__main__":
    unittest.main()
