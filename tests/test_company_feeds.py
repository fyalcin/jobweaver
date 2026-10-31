"""Company job-feed readers (T029): recorded feed samples, no network.

Samples in tests/fixtures/company_feeds are real feeds of 15.10.2026, cut to a few postings.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jobweaver import db

_TMP = tempfile.mkdtemp(prefix="gj-feeds-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

from jobweaver import company_feeds as cf  # noqa: E402
from jobweaver import scrapers  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "company_feeds"


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


def fake_fetch(url, **kwargs):
    if "boards-api.greenhouse.io/v1/boards/bitpanda" in url:
        return _read("greenhouse_sample.json")
    if "prewave.jobs.personio.de/xml" in url:
        return _read("personio_sample.xml")
    if "careers.omv.com/services/rss" in url:
        return _read("successfactors_sample.xml")
    if "/postings?limit=100" in url:
        return _read("smartrecruiters_list.json")
    if "/postings/" in url:
        return _read("smartrecruiters_detail.json")
    raise AssertionError(f"unexpected URL {url}")


GH = {"name": "Bitpanda", "connector": "greenhouse", "identifier": "bitpanda"}
PERSONIO = {"name": "Prewave", "connector": "personio", "identifier": "prewave"}
SF = {"name": "OMV", "connector": "successfactors_rss", "identifier": "careers.omv.com", "location_keyword": "Vienna"}
SR = {"name": "IMS", "connector": "smartrecruiters", "identifier": "IMSNanofabricationGmbH"}


def setUpModule():
    # Discovery imports every module first; point at this module's DB while it runs.
    db.set_db_path(os.path.join(_TMP, "test.db"))


def tearDownModule():
    db.set_db_path(os.path.join(db.DATA_DIR, "jobweaver.db"))  # The runner's disposable default.


class ReaderTest(unittest.TestCase):
    def test_greenhouse(self):
        rows = cf.read_greenhouse(GH, fake_fetch)
        self.assertEqual(len(rows), 3)
        row = rows[0]
        self.assertTrue(row["id"].startswith("feed_greenhouse_bitpanda_"))
        self.assertEqual(row["company"], "Bitpanda")
        self.assertEqual(row["location"], "Vienna, Vienna, Austria")
        self.assertEqual(row["source"], "Company feed (Greenhouse)")
        self.assertEqual(row["company_feed"], "Bitpanda")
        self.assertEqual(row["apply_type"], "external")
        self.assertEqual(row["apply_url"], row["job_url"])
        self.assertTrue(row["job_url"].startswith("https://job-boards.eu.greenhouse.io/bitpanda/jobs/"))
        self.assertEqual(row["language"], "en")
        self.assertTrue(row["posted_date"].startswith("2025-12-02"))
        self.assertNotIn("<", row["description"])  # escaped HTML was decoded and stripped
        self.assertNotIn("&lt;", row["description"])
        self.assertGreater(len(row["description"]), 100)

    def test_personio(self):
        rows = cf.read_personio(PERSONIO, fake_fetch)
        self.assertEqual(len(rows), 2)
        row = rows[0]
        self.assertEqual(row["title"], "B2B Customer Support Specialist (f/m/d)")
        self.assertEqual(row["location"], "Vienna")
        self.assertEqual(row["job_url"], "https://prewave.jobs.personio.de/job/2625679")
        self.assertIn("What we build", row["description"])
        self.assertNotIn("<p", row["description"])
        self.assertTrue(row["posted_date"].startswith("2026-05-06"))

    def test_successfactors_rss_drops_duplicates_and_reads_location_from_title(self):
        rows = cf.read_successfactors_rss(SF, fake_fetch)
        self.assertEqual(len(rows), 2)  # the sample lists the first job twice, like RBI's feed
        row = rows[0]
        self.assertEqual(row["title"], "Expert Data Engineer (gn)")
        self.assertEqual(row["location"], "Vienna, Vienna, AT, 1020")
        self.assertTrue(row["job_url"].startswith("https://careers.omv.com/job/"))
        self.assertNotIn("?", row["job_url"])  # tracking parameters are stripped
        self.assertTrue(row["id"].endswith("_1444824433"))
        self.assertTrue(row["posted_date"].startswith("2026-10-06"))
        self.assertGreater(len(row["description"]), 100)

    def test_smartrecruiters_fetches_detail_only_for_kept_postings(self):
        calls = []

        def counting(url, **kw):
            calls.append(url)
            return fake_fetch(url, **kw)

        keep = lambda stub: "wien" in stub["location"].lower()
        rows = cf.read_smartrecruiters(SR, counting, keep=keep)
        self.assertEqual(len(rows), 1)  # the second posting is in Brunn am Gebirge
        self.assertEqual(sum("/postings/" in c for c in calls), 1)
        row = rows[0]
        self.assertEqual(row["language"], "en")
        self.assertIn("Job Description", row["description"])
        self.assertTrue(row["job_url"].startswith("https://jobs.smartrecruiters.com/IMSNanofabricationGmbH/"))

    def test_unexpected_shapes_raise_feed_error(self):
        with self.assertRaises(cf.FeedError):
            cf.read_greenhouse(GH, lambda url, **kw: '{"unexpected": 1}')
        with self.assertRaises(cf.FeedError):
            cf.read_personio(PERSONIO, lambda url, **kw: "<html>maintenance</html>")
        with self.assertRaises(cf.FeedError):
            cf.read_successfactors_rss(SF, lambda url, **kw: "not xml")
        with self.assertRaises(cf.FeedError):
            cf.read_smartrecruiters(SR, lambda url, **kw: '{"content": 5}')


    def test_successfactors_rss_collapses_same_title_under_two_ids(self):
        feed = _read("successfactors_sample.xml").replace("/1444824433/", "/1444824434/", 1)  # first item's second copy
        rows = cf.read_successfactors_rss(SF, lambda url, **kw: feed)
        self.assertEqual(len(rows), 2)


class FilterTest(unittest.TestCase):
    ROW = {"title": "Data Engineer", "location": "Vienna, Vienna, Austria", "language": "en", "posted_date": "2026-10-10T00:00:00+00:00"}

    def test_location(self):
        self.assertTrue(cf.matches_filters(self.ROW, {}))
        self.assertTrue(cf.matches_filters({**self.ROW, "location": "Remote - Austria"}, {}))
        self.assertTrue(cf.matches_filters({**self.ROW, "location": "Seibersdorf"}, {}))
        self.assertFalse(cf.matches_filters({**self.ROW, "location": "Barcelona, Spain"}, {}))
        self.assertFalse(cf.matches_filters({**self.ROW, "location": ""}, {}))

    def test_title_include_exclude(self):
        self.assertFalse(cf.matches_filters(self.ROW, {"include_titles": ["Scientist"]}))
        self.assertTrue(cf.matches_filters(self.ROW, {"include_titles": ["engineer"]}))
        self.assertFalse(cf.matches_filters(self.ROW, {"exclude_titles": ["^Data"]}))

    def test_english_only(self):
        f = {"english_only": True}
        self.assertTrue(cf.matches_filters(self.ROW, f))
        self.assertFalse(cf.matches_filters({**self.ROW, "language": "de"}, f))
        self.assertFalse(cf.matches_filters({**self.ROW, "language": None, "title": "Sachbearbeiter (m/w/d)"}, f))
        self.assertFalse(cf.matches_filters({**self.ROW, "title": "Developer (w/m/x)"}, f))
        self.assertTrue(cf.matches_filters({**self.ROW, "title": "Developer (all genders)"}, f))
        # off by default: a German ad passes, the German check happens later on the analysed ad
        self.assertTrue(cf.matches_filters({**self.ROW, "language": "de"}, {}))

    def test_max_age(self):
        now = cf.datetime(2026, 10, 15, tzinfo=cf.timezone.utc)
        self.assertTrue(cf.matches_filters(self.ROW, {"max_age_days": 30}, now))
        self.assertFalse(cf.matches_filters(self.ROW, {"max_age_days": 3}, now))
        self.assertTrue(cf.matches_filters({**self.ROW, "posted_date": None}, {"max_age_days": 3}, now))

    def test_rows_missing_required_fields_are_dropped_and_reported(self):
        good = {"id": "a", "title": "T", "company": "C", "job_url": "https://example.invalid/a",
                "description": "Text", "source": "Company feed (Greenhouse)"}
        usable, problems = cf.validate_rows(
            [good, {**good, "id": "b", "job_url": ""}, {**good, "id": "c", "description": ""}], "X [greenhouse]")
        self.assertEqual([r["id"] for r in usable], ["a"])
        self.assertEqual(len(problems), 2)
        self.assertIn("job_url", problems[0])
        self.assertIn("description", problems[1])

    def test_location_is_not_required_but_needed_by_the_location_filter(self):
        row = {**self.ROW, "location": None}
        self.assertFalse(cf.matches_filters(row, {}))
        self.assertTrue(cf.matches_filters({**row, "remote": True}, {}))
        self.assertFalse(cf.matches_filters({**row, "remote": "yes"}, {}))


class KnownElsewhereTest(unittest.TestCase):
    ROWS = [
        {"title": "Data Engineer", "company": "Bitpanda", "job_url": "https://job-boards.eu.greenhouse.io/bitpanda/jobs/1"},
        {"title": "Analyst", "company": "Bitpanda", "job_url": "https://job-boards.eu.greenhouse.io/bitpanda/jobs/2"},
        {"title": "Platform Engineer", "company": "OMV", "job_url": "https://careers.omv.com/job/x/3"},
    ]

    def test_same_title_and_company_from_another_source_is_dropped(self):
        stored = [{"title": "Data Engineer ", "company": "Bitpanda GmbH", "source": "LinkedIn (Apify)"}]
        kept, dropped = cf.drop_known_elsewhere(self.ROWS, stored)
        self.assertEqual((len(kept), dropped), (2, 1))
        self.assertEqual([r["title"] for r in kept], ["Analyst", "Platform Engineer"])

    def test_same_apply_link_is_dropped_even_with_another_title(self):
        stored = [{"title": "Other", "company": "Other", "source": "LinkedIn (Apify)",
                   "apply_url": "https://careers.omv.com/job/x/3?utm_source=li"}]
        kept, dropped = cf.drop_known_elsewhere(self.ROWS, stored)
        self.assertEqual(dropped, 1)
        self.assertNotIn("OMV", [r["company"] for r in kept])

    def test_same_title_at_another_company_is_kept(self):
        stored = [{"title": "Data Engineer", "company": "Dynatrace", "source": "LinkedIn (Apify)"}]
        kept, dropped = cf.drop_known_elsewhere(self.ROWS, stored)
        self.assertEqual(dropped, 0)

    def test_earlier_feed_jobs_are_left_to_the_pipeline(self):
        stored = [{"title": "Data Engineer", "company": "Bitpanda", "source": "Company feed (Greenhouse)"}]
        kept, dropped = cf.drop_known_elsewhere(self.ROWS, stored)
        self.assertEqual(dropped, 0)


class RunTest(unittest.TestCase):
    def test_one_company_failing_does_not_stop_the_others(self):
        def fetch(url, **kw):
            if "personio" in url:
                raise ConnectionError("boom")
            return fake_fetch(url, **kw)

        logs = []
        rows, errors = cf.fetch_company_postings(
            {"filters": {}, "companies": [PERSONIO, GH]}, fetch, log_fn=lambda m, level="info": logs.append((level, m)))
        self.assertEqual({r["company"] for r in rows}, {"Bitpanda"})
        self.assertEqual(len(rows), 2)  # Barcelona is filtered out
        self.assertEqual(len(errors), 1)
        self.assertIn("Prewave", errors[0])
        self.assertTrue(any(level == "error" for level, _ in logs))

    def test_per_company_filters_override_defaults(self):
        config = {"filters": {"english_only": False}, "companies": [{**GH, "english_only": True}]}
        rows, _ = cf.fetch_company_postings(config, fake_fetch)
        self.assertEqual([r["title"] for r in rows], ["Associate, Phone Support - DACH"])

    def test_disabled_company_is_skipped(self):
        rows, errors = cf.fetch_company_postings({"companies": [{**GH, "enabled": False}]}, fake_fetch)
        self.assertEqual((rows, errors), ([], []))

    def test_load_companies(self):
        path = Path(_TMP) / "companies.json"
        path.write_text(json.dumps({"filters": {"english_only": True}, "companies": [GH]}), encoding="utf-8")
        with mock.patch.object(cf, "resolve_user_path", return_value=str(path)):
            self.assertEqual(cf.load_companies("x")["companies"], [GH])
            path.write_text(json.dumps({"companies": [{"name": "X", "connector": "nope", "identifier": "x"}]}), encoding="utf-8")
            with self.assertRaises(cf.FeedError):
                cf.load_companies("x")
            path.write_text(json.dumps({"companies": [{"name": "X", "connector": "greenhouse"}]}), encoding="utf-8")
            with self.assertRaises(cf.FeedError):
                cf.load_companies("x")
        with mock.patch.object(cf, "resolve_user_path", return_value=str(Path(_TMP) / "missing.json")):
            self.assertEqual(cf.load_companies("x"), {"filters": {}, "companies": []})


class PipelineTest(unittest.TestCase):
    """The source plugs into scrape_new_jobs: rows are stored, analysed, and not analysed again on the next run."""

    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.user = db.create_user(f"feeduser_{id(cls)}", password_hash="x", display_name="Feed")

    @classmethod
    def tearDownClass(cls):
        db.delete_user(cls.user["id"])

    def _run(self):
        ai_calls = []

        def ai(description, cv_text=None, model_name=None, denoise=True):
            ai_calls.append(denoise)
            return {"german_level": "none", "requires_german": False, "salary": None, "salary_yearly": None,
                    "skills": "x", "summary": "s", "company_contact": None, "match_score": 50, "description": description}

        config = {"filters": {}, "companies": [GH]}
        with mock.patch.object(cf, "load_companies", return_value=config), \
             mock.patch.object(cf, "http_fetch", side_effect=fake_fetch), \
             mock.patch.object(scrapers, "process_job_with_ai", side_effect=ai):
            result = scrapers.scrape_new_jobs(
                scrapers.ScrapeParams(source="company-feeds", keywords="company feeds"), cv_text="cv", user=self.user)
        return result, ai_calls

    def test_rows_are_stored_with_apply_link_and_not_reanalysed(self):
        # The same job already stored from LinkedIn must not be imported a second time.
        db.upsert_job({"id": "li_999", "job_url": "https://at.linkedin.com/jobs/view/999", "title": "Associate, Phone Support - DACH",
                       "company": "Bitpanda", "source": "LinkedIn (Apify)", "description": "x", "date_scraped": "2026-10-14",
                       "status": "new", "processed": 1}, user_id=self.user["id"])
        result, ai_calls = self._run()
        self.assertTrue(result["success"], result)
        self.assertEqual(result["new_jobs_count"], 1)
        self.assertEqual(ai_calls, [False])  # clean feed text is not denoised
        jobs = db.load_jobs(self.user["id"])
        stored = jobs[jobs["id"].astype(str).str.startswith("feed_greenhouse_")]
        self.assertEqual(len(stored), 1)
        job = db.get_job_by_id(stored.iloc[0]["id"], self.user["id"])
        self.assertEqual(job["apply_type"], "external")
        self.assertTrue(job["apply_url"].startswith("https://job-boards.eu.greenhouse.io/"))
        self.assertEqual(job["company_feed"], "Bitpanda")
        self.assertEqual(job["source"], "Company feed (Greenhouse)")
        result2, ai_calls2 = self._run()
        self.assertEqual(ai_calls2, [])  # same feed again: nothing new, no analysis cost


if __name__ == "__main__":
    unittest.main()
