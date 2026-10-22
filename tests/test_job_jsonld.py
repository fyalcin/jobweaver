"""Reading schema.org JobPosting JSON-LD from a job page, and fetching pages safely."""
import json
import socket
import unittest
from unittest.mock import patch

import job_jsonld
import safe_fetch


def page(*blocks, raw=None):
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks)
    if raw is not None:
        scripts += f'<script type="application/ld+json">{raw}</script>'
    return f"<html><head>{scripts}</head><body><h1>Other</h1></body></html>"


POSTING = {
    "@context": "https://schema.org", "@type": "JobPosting",
    "title": "Software Developer (m/w/d)",
    "description": "<p>We build <b>radio systems</b>.</p><ul><li>Python</li></ul>",
    "datePosted": "2026-10-18T08:20:01.157Z",
    "employmentType": ["FULL_TIME", "PART_TIME"],
    "hiringOrganization": {"@type": "Organization", "name": "Acme GmbH ", "logo": "https://x.invalid/l.png"},
    "jobLocation": [{"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Wien",
                                                    "postalCode": "1020", "addressCountry": "AT"}}],
    "baseSalary": {"@type": "MonetaryAmount", "currency": "EUR",
                   "value": {"@type": "QuantitativeValue", "value": 55356, "unitText": "YEAR"}},
}


class FindTest(unittest.TestCase):
    def test_single_object(self):
        found = job_jsonld.find_job_postings(page(POSTING))
        self.assertEqual(len(found), 1)

    def test_list_graph_and_type_list(self):
        other = {"@type": "Organization", "name": "Acme"}
        self.assertEqual(len(job_jsonld.find_job_postings(page([other, POSTING]))), 1)
        self.assertEqual(len(job_jsonld.find_job_postings(page({"@graph": [other, POSTING]}))), 1)
        self.assertEqual(len(job_jsonld.find_job_postings(page({**POSTING, "@type": ["JobPosting", "Thing"]}))), 1)

    def test_broken_blocks_are_skipped(self):
        self.assertEqual(job_jsonld.find_job_postings(page(raw="{not json")), [])
        self.assertEqual(len(job_jsonld.find_job_postings(page(POSTING, raw="{not json"))), 1)

    def test_no_block(self):
        self.assertEqual(job_jsonld.find_job_postings("<html><p>Hi</p></html>"), [])


class MapTest(unittest.TestCase):
    def test_maps_to_posting_fields(self):
        job = job_jsonld.to_job(POSTING)
        self.assertEqual(job["title"], "Software Developer (m/w/d)")
        self.assertEqual(job["company"], "Acme GmbH")
        self.assertNotIn("<", job["description"])
        self.assertIn("radio systems", job["description"])
        self.assertEqual(job["location"], "Wien, AT")
        self.assertEqual(job["posted_date"], "2026-10-18T08:20:01.157000+00:00")
        self.assertEqual(job["type"], "FULL_TIME, PART_TIME")
        self.assertEqual(job["salary"], "55,356 EUR per year")
        self.assertEqual(job["salary_yearly"], 55356)

    def test_variants(self):
        job = job_jsonld.to_job({**POSTING, "hiringOrganization": "Acme", "employmentType": "Full-time",
                                 "jobLocation": {"address": {"addressLocality": "Graz"}},
                                 "baseSalary": {"currency": "EUR", "value": {"minValue": 3000, "maxValue": 3500,
                                                                              "unitText": "MONTH"}}})
        self.assertEqual(job["company"], "Acme")
        self.assertEqual(job["type"], "Full-time")
        self.assertEqual(job["location"], "Graz")
        self.assertEqual(job["salary"], "3,000 – 3,500 EUR per month")
        self.assertEqual(job["salary_yearly"], 42000)  # the lower bound, ×14 (Austria)

    def test_country_only_place_is_dropped_beside_a_town(self):
        places = [{"address": {"addressLocality": "Wien", "addressCountry": "AT"}}, {"address": {"addressCountry": "AUT"}}]
        self.assertEqual(job_jsonld.to_job({**POSTING, "jobLocation": places})["location"], "Wien, AT")
        self.assertEqual(job_jsonld.to_job({**POSTING, "jobLocation": [places[1]]})["location"], "AUT")

    def test_remote_and_missing_parts(self):
        job = job_jsonld.to_job({"@type": "JobPosting", "title": "Remote role", "jobLocationType": "TELECOMMUTE"})
        self.assertIs(job["remote"], True)
        self.assertNotIn("location", job)
        self.assertNotIn("salary", job)

    def test_non_eur_salary_has_no_yearly_eur(self):
        job = job_jsonld.to_job({**POSTING, "baseSalary": {"currency": "USD", "value": {"value": 90000, "unitText": "YEAR"}}})
        self.assertEqual(job["salary"], "90,000 USD per year")
        self.assertNotIn("salary_yearly", job)

    def test_strange_values_do_not_crash(self):
        for bad in ({"title": ["a"], "hiringOrganization": 5, "jobLocation": "Wien", "baseSalary": "lots"},
                    {"jobLocation": [None, 3], "baseSalary": {"value": "n/a"}, "employmentType": [None]}):
            job_jsonld.to_job({**POSTING, **bad})


class SafeFetchTest(unittest.TestCase):
    def test_only_http_and_https(self):
        for url in ("file:///etc/passwd", "ftp://example.org/x", "gopher://x", "example.org/job"):
            with self.assertRaises(safe_fetch.UnsafeURL):
                safe_fetch.check_url(url)

    def test_private_addresses_are_refused(self):
        for url in ("http://127.0.0.1:8000/api", "http://10.0.0.5/", "http://192.168.1.1/", "http://[::1]/",
                    "http://169.254.169.254/latest/meta-data", "http://0.0.0.0/", "http://100.100.100.100/"):
            with self.assertRaises(safe_fetch.UnsafeURL, msg=url):
                safe_fetch.check_url(url)

    def test_hostname_resolving_to_a_private_address_is_refused(self):
        fake = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.10", 80))]
        with patch("safe_fetch.socket.getaddrinfo", return_value=fake):
            with self.assertRaises(safe_fetch.UnsafeURL):
                safe_fetch.check_url("http://jobs.example.org/1")

    def test_public_hostname_passes(self):
        fake = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
        with patch("safe_fetch.socket.getaddrinfo", return_value=fake):
            safe_fetch.check_url("https://jobs.example.org/1")

    def test_redirect_to_a_private_address_is_refused(self):
        class Response:
            def __init__(self, status, location=None):
                self.status_code, self.headers, self.text, self.url = status, {"Location": location} if location else {}, "", ""
                self.is_redirect = status in (301, 302, 303, 307, 308)
            def raise_for_status(self):
                pass
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
        with patch("safe_fetch.socket.getaddrinfo", return_value=public), \
             patch("safe_fetch.requests.get", return_value=Response(302, "http://127.0.0.1:8000/api/jobs")):
            with self.assertRaises(safe_fetch.UnsafeURL):
                safe_fetch.fetch_page("https://jobs.example.org/1")

    def test_identifies_itself_honestly(self):
        seen = {}
        class Response:
            status_code, headers, text, url, is_redirect = 200, {}, "<html></html>", "https://jobs.example.org/1", False
            def raise_for_status(self):
                pass
        def get(url, **kwargs):
            seen.update(kwargs["headers"])
            return Response()
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
        with patch("safe_fetch.socket.getaddrinfo", return_value=public), patch("safe_fetch.requests.get", side_effect=get):
            safe_fetch.fetch_page("https://jobs.example.org/1")
        self.assertTrue(seen["User-Agent"].startswith("Jobweaver/"))
        self.assertNotIn("Mozilla", seen["User-Agent"])


if __name__ == "__main__":
    unittest.main()
