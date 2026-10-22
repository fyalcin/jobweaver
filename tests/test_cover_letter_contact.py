import unittest
from unittest.mock import patch
from scrapers import process_job_with_ai


class TestCoverLetterContact(unittest.TestCase):

    @patch("scrapers.run_ai_prompt")
    def test_process_job_with_ai_extracts_contact(self, mock_ai_prompt):
        mock_ai_prompt.return_value = """{
            "german_level": "B1",
            "minimum_salary": "€3,889",
            "skills": "Materials science, physics",
            "summary": "Process development role",
            "company_contact": "Frau Ursula Popp",
            "match_score": 88
        }"""
        res = process_job_with_ai("Bewerbungen per E-Mail an Frau Ursula Popp", "CV text")
        self.assertEqual(res["company_contact"], "Frau Ursula Popp")
        self.assertEqual(res["german_level"], "B1")
        self.assertEqual(res["match_score"], 88)


if __name__ == "__main__":
    unittest.main()
