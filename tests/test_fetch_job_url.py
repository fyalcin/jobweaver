"""The URL import: JSON-LD first, page heuristics as fallback, and no fetches of private addresses."""
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import safe_fetch
import server


class Page:
    def __init__(self, text):
        self.text = text


POSTING = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Data Engineer",
           "description": "<p>Pipelines in Python.</p>", "hiringOrganization": {"name": "Acme"},
           "jobLocation": {"address": {"addressLocality": "Wien"}}, "datePosted": "2026-10-20"}
USER = {"id": 1, "username": "synthetic"}


class FetchJobUrlTest(unittest.TestCase):
    def fetch(self, html, url="https://jobs.example.org/1"):
        with patch("safe_fetch.fetch_page", return_value=Page(html)):
            return server.fetch_job_url(server.FetchJobUrlRequest(url=url), user=USER)

    def test_json_ld_is_read_first(self):
        html = f'<html><head><script type="application/ld+json">{json.dumps(POSTING)}</script></head>' \
               '<body><h1>Careers at Acme</h1></body></html>'
        result = self.fetch(html)
        self.assertEqual(result["title"], "Data Engineer")
        self.assertEqual(result["company"], "Acme")
        self.assertEqual(result["location"], "Wien")
        self.assertIn("Pipelines in Python.", result["description"])

    def test_page_without_json_ld_falls_back_to_heuristics(self):
        result = self.fetch("<html><head><title>X</title></head><body><h1>Platform Engineer</h1><p>Kubernetes.</p></body></html>")
        self.assertEqual(result["title"], "Platform Engineer")
        self.assertIn("Kubernetes.", result["description"])

    def test_private_address_is_refused_with_a_clear_message(self):
        with self.assertRaises(HTTPException) as caught:
            server.fetch_job_url(server.FetchJobUrlRequest(url="http://127.0.0.1:8000/api/jobs"), user=USER)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("cannot be fetched", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
