"""Mappings into the Posting fields: stable IDs only, and nothing beyond the schema (ADR-0006)."""
import unittest

from jobweaver import postings
from jobweaver import scrapers


class StableIdTest(unittest.TestCase):
    def test_no_random_ids(self):
        self.assertEqual(scrapers._karriere_job_id_from_url("https://www.karriere.at/jobs/7654321"), "karriere_7654321")
        for url in (None, "", "https://www.karriere.at/f/acme"):
            self.assertEqual(scrapers._karriere_job_id_from_url(url), "")
            self.assertEqual(scrapers._karriere_job_id_from_url(url), scrapers._karriere_job_id_from_url(url))
        self.assertEqual(scrapers._linkedin_bebity_item_to_job({"jobUrl": "https://x.invalid"})["id"], "")
        self.assertEqual(scrapers._linkedin_legacy_item_to_job({"link": "https://x.invalid"})["id"], "")

    def test_record_without_source_id_is_rejected(self):
        job = scrapers._linkedin_bebity_item_to_job({"jobUrl": "https://www.linkedin.com/jobs/view/1", "title": "T",
                                                      "companyName": "C", "description": "Text"})
        _, reason = postings.to_posting({**job, "source": "LinkedIn (Apify)"})
        self.assertIn("id", reason)


if __name__ == "__main__":
    unittest.main()
