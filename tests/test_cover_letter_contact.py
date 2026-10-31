import unittest
from unittest.mock import patch
from jobweaver.scrapers import process_job_with_ai


class TestCoverLetterContact(unittest.TestCase):

    @patch("jobweaver.scrapers.run_ai_prompt")
    def test_process_job_with_ai_extracts_contact(self, mock_ai_prompt):
        mock_ai_prompt.return_value = """{
            "german_level": "B1",
            "minimum_salary": "€3,889",
            "skills": "Materials science, physics",
            "summary": "Process development role",
            "company_contact": "Frau Ursula Popp",
            "match_checks": []
        }"""
        res = process_job_with_ai("Bewerbungen per E-Mail an Frau Ursula Popp", "CV text")
        self.assertEqual(res["company_contact"], "Frau Ursula Popp")
        self.assertEqual(res["german_level"], "B1")
        self.assertIsNone(res["match_score"])
        self.assertEqual(res["match_rating"], "Unrated")


if __name__ == "__main__":
    unittest.main()
