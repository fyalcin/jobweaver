"""The gate every Source's records pass before storage (ADR-0006)."""
import datetime as dt
import math
import unittest

from jobweaver import postings

FULL = {
    "id": "feed_greenhouse_acme_1",
    "source": "Company feed (Greenhouse)",
    "job_url": "https://boards.example.invalid/acme/jobs/1",
    "title": "  Data Engineer ",
    "company": "Acme",
    "description": "We build pipelines. " * 30,
}


class ToPostingTest(unittest.TestCase):
    def test_complete_record_becomes_posting_with_trimmed_text(self):
        posting, reason = postings.to_posting(dict(FULL))
        self.assertIsNone(reason)
        self.assertEqual(posting["title"], "Data Engineer")

    def test_each_required_field_is_required(self):
        for field in postings.REQUIRED:
            for empty in (None, "", "   ", float("nan")):
                posting, reason = postings.to_posting({**FULL, field: empty})
                self.assertIsNone(posting, field)
                self.assertIn(field, reason)

    def test_reason_names_every_missing_field(self):
        _, reason = postings.to_posting({"id": "x", "source": "S"})
        for field in ("job_url", "title", "company", "description"):
            self.assertIn(field, reason)

    def test_url_must_be_http(self):
        for url in ("ftp://example.invalid/1", "javascript:alert(1)", "/jobs/1"):
            posting, reason = postings.to_posting({**FULL, "job_url": url})
            self.assertIsNone(posting)
            self.assertIn("job_url", reason)

    def test_unknown_fields_never_reach_the_database(self):
        posting, _ = postings.to_posting({**FULL, "emails": ["recruiter@example.invalid"],
                                          "company_rating": 4.1, "experience": "3 years"})
        self.assertNotIn("emails", posting)
        self.assertNotIn("company_rating", posting)
        self.assertNotIn("experience", posting)

    def test_optional_fields_are_kept(self):
        record = {**FULL, "location": "Wien", "apply_url": "https://acme.example.invalid/apply",
                  "apply_type": "external", "type": "Vollzeit", "salary": "€ 4.000 brutto",
                  "salary_yearly": 56000, "language": "de", "company_feed": "Acme", "remote": True}
        posting, _ = postings.to_posting(record)
        for field in ("location", "apply_url", "apply_type", "type", "salary", "salary_yearly",
                      "language", "company_feed", "remote"):
            self.assertEqual(posting[field], record[field], field)

    def test_missing_location_is_accepted(self):
        posting, reason = postings.to_posting(dict(FULL))
        self.assertIsNone(reason)
        self.assertNotIn("location", posting)

    def test_bad_dates_become_empty_good_ones_iso(self):
        cases = {
            "2026-10-20": "2026-10-20",
            "2026-10-20T08:00:00+02:00": "2026-10-20T08:00:00+02:00",
            dt.date(2026, 10, 20): "2026-10-20",
            dt.datetime(2026, 10, 20, 8, 0): "2026-10-20T08:00:00",
            "vor 2 Tagen": None,
            "": None,
            float("nan"): None,
        }
        for value, expected in cases.items():
            posting, reason = postings.to_posting({**FULL, "posted_date": value})
            self.assertIsNone(reason, value)
            self.assertEqual(posting.get("posted_date"), expected, value)

    def test_bad_salary_numbers_become_empty(self):
        for value in ("about 50k", -1, 0, float("nan"), True):
            posting, reason = postings.to_posting({**FULL, "salary_yearly": value})
            self.assertIsNone(reason)
            self.assertNotIn("salary_yearly", posting)
        posting, _ = postings.to_posting({**FULL, "salary_yearly": "56000"})
        self.assertEqual(posting["salary_yearly"], 56000)

    def test_bad_optional_url_is_dropped_not_rejected(self):
        posting, reason = postings.to_posting({**FULL, "apply_url": "mailto:jobs@example.invalid"})
        self.assertIsNone(reason)
        self.assertNotIn("apply_url", posting)

    def test_html_description_becomes_text(self):
        posting, _ = postings.to_posting({**FULL, "description": "<p>Build <b>pipelines</b></p><ul><li>Python</li></ul>" + "x" * 300})
        self.assertNotIn("<", posting["description"])
        self.assertIn("pipelines", posting["description"])

    def test_remote_must_be_a_real_boolean(self):
        posting, _ = postings.to_posting({**FULL, "remote": "maybe"})
        self.assertNotIn("remote", posting)
        posting, _ = postings.to_posting({**FULL, "remote": float("nan")})
        self.assertNotIn("remote", posting)


class GateTest(unittest.TestCase):
    def test_splits_postings_and_rejected_records_with_reasons(self):
        result = postings.gate([dict(FULL), {**FULL, "id": "", "title": "No id"}], "Acme feed")
        self.assertEqual(len(result.postings), 1)
        self.assertEqual(len(result.rejected), 1)
        rejected = result.rejected[0]
        self.assertEqual(rejected["source"], "Acme feed")
        self.assertEqual(rejected["title"], "No id")
        self.assertIn("id", rejected["reason"])

    def test_short_descriptions_are_counted_not_rejected(self):
        result = postings.gate([{**FULL, "description": "Too short"}], "S")
        self.assertEqual(len(result.postings), 1)
        self.assertEqual(result.short_descriptions, 1)

    def test_summary_is_quiet_when_nothing_was_rejected(self):
        self.assertIsNone(postings.gate([dict(FULL)], "S").summary())

    def test_summary_names_reasons_and_examples(self):
        result = postings.gate([{**FULL, "id": f"x{i}", "description": "", "title": f"Job {i}"} for i in range(7)], "S")
        level, message = result.summary()
        self.assertIn("7 of 7", message)
        self.assertIn("description", message)
        self.assertIn("Job 0", message)
        self.assertNotIn("Job 6", message)  # examples are capped

    def test_many_rejections_warn_that_the_source_changed_shape(self):
        records = [dict(FULL, id=str(i)) for i in range(6)] + [{**FULL, "id": f"bad{i}", "company": ""} for i in range(4)]
        level, message = postings.gate(records, "S").summary()
        self.assertEqual(level, "error")
        self.assertIn("changed", message)

    def test_a_few_rejections_are_a_warning(self):
        records = [dict(FULL, id=str(i)) for i in range(19)] + [{**FULL, "id": "bad", "company": ""}]
        level, _ = postings.gate(records, "S").summary()
        self.assertEqual(level, "warning")

    def test_pandas_style_missing_values(self):
        posting, reason = postings.to_posting({**FULL, "location": math.nan, "salary": None})
        self.assertIsNone(reason)
        self.assertNotIn("location", posting)
        self.assertNotIn("salary", posting)


if __name__ == "__main__":
    unittest.main()
