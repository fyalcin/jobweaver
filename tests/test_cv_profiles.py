import os
import shutil
import tempfile
import unittest
from unittest import mock

import cv_profiles
from cv_profiles import (
    PROFILES,
    select_cv_profile,
    profile_template,
    profile_compact_template,
    profile_label,
    available_profiles,
    normalize_profile,
)


class TestCvProfiles(unittest.TestCase):
    def tearDown(self):
        cv_profiles._user_profiles_cache.clear()

    def test_research_profile(self):
        result = select_cv_profile(
            {"title": "Research Software Engineer", "description": "Python HPC simulation workflows with Slurm"}
        )
        self.assertEqual(result["profile"], "research")

    def test_industry_profile(self):
        result = select_cv_profile(
            {"title": "Python Backend Developer", "description": "REST API, Docker, database and automation"}
        )
        self.assertEqual(result["profile"], "industry")

    def test_manual_override(self):
        result = select_cv_profile({"title": "Python Backend Developer"}, "research")
        self.assertEqual(result["profile"], "research")
        self.assertEqual(result["confidence"], 1.0)

    def test_tie_falls_back_to_default_profile(self):
        # No keywords match either profile -> flagged default (industry) wins.
        result = select_cv_profile({"title": "Sales Manager", "description": "Call customers"})
        self.assertEqual(result["profile"], "industry")
        self.assertEqual(result["confidence"], 0.0)

    def test_compact_templates_exist(self):
        for profile_id in PROFILES:
            compact_tpl = profile_compact_template(profile_id)
            std_tpl = profile_template(profile_id)
            self.assertTrue(os.path.exists(compact_tpl), f"Missing compact template: {compact_tpl}")
            self.assertTrue(os.path.exists(std_tpl), f"Missing standard template: {std_tpl}")
            self.assertIn("compact", compact_tpl)

    def test_normalize_profile(self):
        self.assertEqual(normalize_profile("research"), "research")
        self.assertEqual(normalize_profile("industry"), "industry")
        self.assertIsNone(normalize_profile("invalid"))
        self.assertIsNone(normalize_profile(None))


class TestPerUserProfileOverrides(unittest.TestCase):
    """profiles/<user>/cv_profiles.py drives that user's dropdown + auto-selection."""

    SECOND_USER_PROFILES = '''
PROFILES = {
    "retail": {
        "label": "Einzelhandel & Filialmanagement",
        "template": "base-cv-tex/base-cv.tex",
        "compact_template": "base-cv-tex/base-cv.tex",
        "instruction": "Retail operations.",
        "terms": {"einzelhandel", "kassa", "filial", "marktmanager", "kundenservice"},
        "default": True,
    },
    "analytics": {
        "label": "Datenanalyse & Wissenschaft",
        "template": "base-cv-tex/base-cv.tex",
        "compact_template": "base-cv-tex/base-cv.tex",
        "instruction": "Data analysis.",
        "terms": {"datenanalyse", "kpi", "statistik"},
        "hints": {"wissenschaftliche", "forschung"},
    },
}
'''

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-profiles-test-")
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)
        patcher = mock.patch.object(cv_profiles, "user_profile_dir", lambda u: os.path.join(self.tmp_dir, u or ""))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(cv_profiles._user_profiles_cache.clear)

    def _write_override(self, username):
        user_dir = os.path.join(self.tmp_dir, username)
        os.makedirs(user_dir)
        with open(os.path.join(user_dir, "cv_profiles.py"), "w", encoding="utf-8") as f:
            f.write(self.SECOND_USER_PROFILES)

    def test_override_drives_available_profiles(self):
        self._write_override("sam")
        ids = [p["id"] for p in available_profiles("sam")]
        self.assertEqual(ids, ["retail", "analytics"])
        self.assertEqual(profile_label("retail", "sam"), "Einzelhandel & Filialmanagement")
        # Users without an override keep the root profiles
        self.assertEqual([p["id"] for p in available_profiles("admin")], ["research", "industry"])

    def test_override_auto_selection_uses_profile_terms(self):
        self._write_override("sam")
        result = select_cv_profile(
            {"title": "Verkäufer/in mit Kassa-Erfahrung", "description": "Einzelhandel, Kundenservice, Filialabläufe"},
            user="sam",
        )
        self.assertEqual(result["profile"], "retail")
        result = select_cv_profile({"title": "Data Analyst", "description": "Datenanalyse, KPIs und Statistik"}, user="sam")
        self.assertEqual(result["profile"], "analytics")

    def test_override_tie_falls_back_to_flagged_default(self):
        self._write_override("sam")
        result = select_cv_profile({"title": "Office Allrounder", "description": "Telefon und Post"}, user="sam")
        self.assertEqual(result["profile"], "retail")
        self.assertEqual(result["confidence"], 0.0)

    def test_normalize_respects_override(self):
        self._write_override("sam")
        self.assertEqual(normalize_profile("retail", "sam"), "retail")
        self.assertIsNone(normalize_profile("retail"))  # root has no retail profile
        self.assertIsNone(normalize_profile("research", "sam"))


if __name__ == "__main__":
    unittest.main()


