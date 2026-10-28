import json
import unittest
from unittest import mock

import scrapers


class StructuredJobExtractionTest(unittest.TestCase):
    def test_process_job_with_ai_extracts_structured_fields(self):
        fake_ai_output = json.dumps({
            "german_level": "B1",
            "minimum_salary": "ab € 50.000 / Jahr",
            "salary_amount": 50000,
            "salary_period": "year",
            "skills": "Python, Linux, Git",
            "summary": "Deploying multi-beam mask writer software for semiconductor manufacturing.",
            "work_model": "Hybrid (Home Office)",
            "experience_years": "3 years",
            "education_level": "Bachelor's degree",
            "tools_technologies": ["Python", "Linux", "Git"],
            "requirements": [
                "Technical degree or 3 years experience",
                "Very good Linux OS knowledge",
                "Solid networking fundamentals"
            ],
            "tasks": [
                "Deploy and integrate multi-beam mask writer software",
                "Perform software and configuration upgrades"
            ],
            "company_summary": "Global leader in semiconductor manufacturing technology.",
            "company_contact": "Dr. Thomas Meier",
            "match_checks": [{"requirement": "Python", "importance": "must", "posting_quote": "Python required", "coverage": "shown", "cv_quote": "Python experience"}],
            "match_analysis": {
                "tier": "Good Match",
                "synthesis": "Strong match due to Python and Linux proficiency.",
                "strengths": [
                    {"title": "Python & Linux Proficiency", "detail": "Extensive experience matches requirements."}
                ],
                "gaps": [
                    {"title": "Limited Hardware Integration", "detail": "Hardware interfacing not demonstrated."}
                ],
                "tips": [
                    {"title": "Emphasize Adaptability", "detail": "Highlight fast learning in integration."}
                ]
            }
        })

        with mock.patch("scrapers.run_ai_prompt", return_value=fake_ai_output):
            res = scrapers.process_job_with_ai("Python required. Test job description", cv_text="Python experience")

        self.assertEqual(res["german_level"], "B1")
        self.assertEqual(res["salary_yearly"], 50000)
        self.assertEqual(res["work_model"], "Hybrid (Home Office)")
        self.assertEqual(res["experience_years"], "3 years")
        self.assertEqual(res["education_level"], "Bachelor's degree")
        self.assertEqual(res["tools_technologies"], ["Python", "Linux", "Git"])
        self.assertEqual(len(res["requirements"]), 3)
        self.assertEqual(len(res["tasks"]), 2)
        self.assertEqual(res["company_contact"], "Dr. Thomas Meier")
        self.assertIsNone(res["match_score"])
        self.assertEqual(res["match_rating"], "Great")
        self.assertEqual(res["match_analysis"]["tier"], "Great")
        self.assertEqual(len(res["match_analysis"]["strengths"]), 1)
        self.assertEqual(len(res["match_analysis"]["gaps"]), 1)
        self.assertEqual(len(res["match_analysis"]["tips"]), 1)

    def test_process_job_with_ai_fallback_defaults(self):
        # Old/minimal output without structured fields
        minimal_output = json.dumps({
            "german_level": "none",
            "minimum_salary": "Not Specified",
            "skills": "Python, SQL",
            "summary": "Backend developer role.",
            "match_checks": []
        })

        with mock.patch("scrapers.run_ai_prompt", return_value=minimal_output):
            res = scrapers.process_job_with_ai("Python required. Test job description", cv_text="Python experience")

        self.assertEqual(res["german_level"], "none")
        self.assertFalse(res["requires_german"])
        self.assertEqual(res["work_model"], "Unknown")
        self.assertEqual(res["experience_years"], "Not Specified")
        self.assertEqual(res["education_level"], "Not Specified")
        self.assertEqual(res["tools_technologies"], ["Python", "SQL"])
        self.assertEqual(res["requirements"], [])
        self.assertEqual(res["tasks"], [])
        self.assertIsNone(res["company_summary"])
        self.assertIsNone(res["match_score"])
        self.assertEqual(res["match_rating"], "Unrated")
        self.assertIsInstance(res["match_analysis"], dict)
        self.assertEqual(res["match_analysis"]["tier"], "Unrated")
        self.assertEqual(res["match_analysis"]["strengths"], [])
        self.assertEqual(res["match_analysis"]["gaps"], [])
        self.assertEqual(res["match_analysis"]["tips"], [])

    def test_build_analysis_prompt_includes_intent_rules(self):
        prompt_with_cv = scrapers._build_analysis_prompt("Job text", cv_text="Candidate CV content", include_cleanup=False)
        self.assertIn("Standing Notes", prompt_with_cv)
        self.assertIn("preference_conflicts", prompt_with_cv)
        self.assertIn("Candidate CV:\nCandidate CV content", prompt_with_cv)

        prompt_no_cv = scrapers._build_analysis_prompt("Job text", cv_text=None, include_cleanup=False)
        self.assertNotIn("Standing Notes", prompt_no_cv)
        self.assertNotIn("Candidate CV:", prompt_no_cv)


if __name__ == "__main__":
    unittest.main()
