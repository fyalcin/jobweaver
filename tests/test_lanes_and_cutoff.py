"""Cut-off ad texts and extra search lanes (15.10.2026).

A browser-based reader once stored only the first half of some ads, so the German requirement was missing and
the job looked like a clean fit. Ads without a requirements section are now held for review. Extra lanes (e.g. bridge
jobs) scrape other keywords with a small total limit and tag their rows.
"""
import os
import tempfile
import unittest
from unittest import mock

import pandas as pd

from jobweaver import db

_TMP = tempfile.mkdtemp(prefix="gj-lanes-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

from jobweaver import daily_scraper  # noqa: E402
from jobweaver import job_policy  # noqa: E402


FULL_AD = ("Wir suchen eine:n Python-Entwickler:in in Wien. Deine Aufgaben: Datenpipelines betreuen. "
           "Dein Profil: abgeschlossenes Studium, sehr gute Deutschkenntnisse (C1).")
CUT_AD = "Wir suchen eine:n Python-Entwickler:in in Wien. Deine Aufgaben: Datenpipelines betreuen und Kunden beraten."
ENGLISH_AD = "Join our team in Vienna. What you bring: Python, SQL and curiosity."


def setUpModule():
    # Discovery imports every module first; point at this module's DB while it runs.
    db.set_db_path(os.path.join(_TMP, "test.db"))


def tearDownModule():
    db.set_db_path(os.path.join(db.DATA_DIR, "jobweaver.db"))  # The runner's disposable default.


class DescriptionIncompleteTest(unittest.TestCase):
    def test_ad_with_requirements_section_is_complete(self):
        self.assertFalse(job_policy.description_incomplete(FULL_AD))
        self.assertFalse(job_policy.description_incomplete(ENGLISH_AD))

    def test_ad_without_requirements_section_is_incomplete(self):
        self.assertTrue(job_policy.description_incomplete(CUT_AD))

    def test_empty_text_is_not_flagged_here(self):
        # Empty descriptions are handled by acquisition_state, not by this check.
        self.assertFalse(job_policy.description_incomplete(""))
        self.assertFalse(job_policy.description_incomplete(None))

    def test_flagged_job_needs_review_instead_of_eligible(self):
        job = {"german_level": "none", "german_strength": "none", "constraints": []}
        self.assertEqual(job_policy.eligibility(job, {})["state"], "eligible")
        job["description_incomplete"] = True
        result = job_policy.eligibility(job, {})
        self.assertEqual(result["state"], "needs_review")
        self.assertIn(job_policy.INCOMPLETE_DESCRIPTION, result["unknowns"])


class LanesTest(unittest.TestCase):
    def _run(self, config):
        calls = []
        with mock.patch.object(daily_scraper, "load_config", return_value=config), \
             mock.patch.object(daily_scraper, "load_effective_cv", return_value="CV text"), \
             mock.patch.object(daily_scraper, "resolve_scrape_model", return_value="test-model"), \
             mock.patch.object(daily_scraper, "scrape_new_jobs", side_effect=lambda params, **kw: calls.append(params)), \
             mock.patch.object(daily_scraper, "retry_failed_analyses", return_value=(0, 0)), \
             mock.patch.object(daily_scraper.db, "load_jobs_by_date", return_value=pd.DataFrame()):
            daily_scraper._run_daily_for_user({"id": 1, "username": "tester"})
        return calls

    def test_lane_splits_its_total_limit_and_tags_rows(self):
        config = {"daily_scraper": {
            "enable_linkedin": False, "enable_karriere": False,
            "lanes": [{"name": "bridge", "source": "karriere-apify",
                       "keywords": ["Kundenservice Türkisch", "Back Office"], "results_limit": 10}]}}
        calls = self._run(config)
        self.assertEqual([c.keywords for c in calls], ["Kundenservice Türkisch", "Back Office"])
        self.assertEqual({c.results_limit for c in calls}, {5})
        self.assertEqual({c.lane for c in calls}, {"bridge"})
        self.assertEqual({c.source for c in calls}, {"karriere-apify"})

    def test_lane_without_keywords_is_skipped(self):
        config = {"daily_scraper": {
            "enable_linkedin": False, "enable_karriere": False,
            "lanes": [{"name": "empty", "keywords": []}]}}
        self.assertEqual(self._run(config), [])

    def test_main_sources_carry_no_lane(self):
        config = {"daily_scraper": {"enable_linkedin": True, "enable_karriere": False}}
        calls = self._run(config)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0].lane)


if __name__ == "__main__":
    unittest.main()
