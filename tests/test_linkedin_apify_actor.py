import os
import shutil
import tempfile
import unittest
from unittest import mock

from jobweaver import db

# Point db at a throwaway SQLite file BEFORE importing scrapers.
_TMP = tempfile.mkdtemp(prefix="gj-li-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

from jobweaver import scrapers  # noqa: E402

BEBITY = scrapers.LINKEDIN_ACTOR_BEBITY
LEGACY = scrapers.LINKEDIN_ACTOR_LEGACY


def _bebity_item(**overrides):
    """A bebity/linkedin-jobs-scraper record (fields as returned on 12.10.2026)."""
    job_id = overrides.get("id", "4477281803")
    item = {
        "id": job_id,
        "jobUrl": f"https://at.linkedin.com/jobs/view/applied-ai-engineer-at-accenture-{job_id}?trk=public_jobs_topcard-title",
        "title": "Applied AI Engineer (all genders)",
        "companyName": "Accenture DACH",
        "location": "Vienna, Vienna, Austria",
        "description": "Build and ship applied AI systems for clients. " * 12,
        "salary": "",
        "applyType": "EXTERNAL",
        "applyUrl": "https://www.accenture.com/at-de/careers/jobdetails?id=R00350",
        "publishedAt": "2026-10-12",
    }
    item.update(overrides)
    return item


def _legacy_item(**overrides):
    job_id = overrides.get("id", "4400000001")
    item = {
        "id": job_id,
        "link": f"https://at.linkedin.com/jobs/view/python-developer-at-acme-{job_id}?position=1&pageNum=0",
        "title": "Python Developer",
        "companyName": "Acme",
        "location": "Vienna, Austria",
        "descriptionText": "We need a Python developer for scientific workflows. " * 12,
        "salaryInfo": ["EUR 60,000", "EUR 70,000"],
    }
    item.update(overrides)
    return item


def setUpModule():
    # Discovery imports every module first; point at this module's DB while it runs.
    db.set_db_path(os.path.join(_TMP, "test.db"))


def tearDownModule():
    db.set_db_path(os.path.join(db.DATA_DIR, "jobweaver.db"))  # The runner's disposable default.


class _FakeDataset:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        return iter(list(self._items))


class _FakeActor:
    def __init__(self, client, actor_id):
        self._client = client
        self._actor_id = actor_id

    def call(self, run_input=None):
        self._client.calls.append((self._actor_id, run_input or {}))
        if self._actor_id in self._client.failing:
            raise RuntimeError(f"{self._actor_id} exploded")
        return {"defaultDatasetId": self._actor_id}


class _FakeApifyClient:
    def __init__(self, token):
        self.calls = []
        self.items = {}
        self.failing = set()

    def actor(self, actor_id):
        return _FakeActor(self, actor_id)

    def dataset(self, dataset_id):
        return _FakeDataset(self.items.get(dataset_id, []))


def _run_scrape(user, items, failing=(), keywords="Python Developer, Data Engineer"):
    ai_calls = []

    def ai(description, cv_text=None, model_name=None, denoise=True):
        ai_calls.append(description)
        return {
            "german_level": "none", "requires_german": False, "salary": "AI Salary",
            "salary_yearly": None, "skills": "x", "summary": "s", "company_contact": None,
            "match_score": 50, "description": description,
        }

    holder = {}

    def factory(token):
        client = _FakeApifyClient(token)
        client.items = items
        client.failing = set(failing)
        client.ai_calls = ai_calls
        holder["client"] = client
        return client

    with mock.patch.dict(os.environ, {"APIFY_API_TOKEN": "token-test"}), \
         mock.patch("apify_client.ApifyClient", factory), \
         mock.patch.object(scrapers, "process_job_with_ai", side_effect=ai):
        result = scrapers.scrape_new_jobs(
            scrapers.ScrapeParams(results_limit=9, hours_old=24, keywords=keywords, source="linkedin-apify"),
            cv_text="cv", user=user,
        )
    return result, holder["client"]


class LinkedInBebityMapperTest(unittest.TestCase):
    def test_external_job_keeps_company_url(self):
        job = scrapers._linkedin_bebity_item_to_job(_bebity_item())
        self.assertEqual(job["id"], "li_4477281803")
        self.assertEqual(job["apply_type"], "external")
        self.assertEqual(job["apply_url"], "https://www.accenture.com/at-de/careers/jobdetails?id=R00350")
        self.assertEqual(job["company"], "Accenture DACH")
        self.assertIsNone(job["salary"])

    def test_easy_apply_has_no_apply_url(self):
        job = scrapers._linkedin_bebity_item_to_job(_bebity_item(
            applyType="EASY_APPLY", applyUrl="https://at.linkedin.com/jobs/view/some-job-4477281803"))
        self.assertEqual(job["apply_type"], "easy_apply")
        self.assertIsNone(job["apply_url"])

    def test_external_without_link_stays_external(self):
        for value in ("", None):
            job = scrapers._linkedin_bebity_item_to_job(_bebity_item(applyUrl=value))
            self.assertEqual(job["apply_type"], "external")
            self.assertIsNone(job["apply_url"])

    def test_linkedin_address_is_never_a_company_url(self):
        job = scrapers._linkedin_bebity_item_to_job(_bebity_item(applyUrl="https://www.linkedin.com/jobs/view/4477281803"))
        self.assertIsNone(job["apply_url"])

    def test_unknown_label_gives_no_url(self):
        job = scrapers._linkedin_bebity_item_to_job(_bebity_item(applyType=None))
        self.assertIsNone(job["apply_type"])
        self.assertIsNone(job["apply_url"])

    def test_every_key_present_so_dataframes_have_no_gaps(self):
        keys = set(scrapers._linkedin_bebity_item_to_job(_bebity_item()))
        for override in ({"applyUrl": ""}, {"applyType": "EASY_APPLY"}, {"salary": "EUR 60,000"}):
            self.assertEqual(set(scrapers._linkedin_bebity_item_to_job(_bebity_item(**override))), keys)

    def test_legacy_mapping_unchanged(self):
        job = scrapers._linkedin_legacy_item_to_job(_legacy_item())
        self.assertEqual(job["salary"], "EUR 60,000, EUR 70,000")
        self.assertEqual(job["id"], "li_4400000001")
        self.assertNotIn("apply_url", job)


class LinkedInSearchUrlTest(unittest.TestCase):
    def test_same_url_as_before_the_refactor(self):
        urls = scrapers._linkedin_search_urls("Data Engineer OR Python Developer", "Vienna, AT", 24, 10)
        self.assertEqual(urls, [
            "https://www.linkedin.com/jobs/search/?keywords=Data+Engineer+OR+Python+Developer"
            "&location=Vienna%2C+AT&f_TPR=r86400&f_JT=F&distance=10"])

    def test_one_url_per_comma_separated_phrase(self):
        urls = scrapers._linkedin_search_urls("Python Developer, Data Engineer", "Vienna, AT", 48, 25)
        self.assertEqual(len(urls), 2)
        self.assertIn("keywords=Data+Engineer", urls[1])
        self.assertIn("f_TPR=r172800", urls[1])
        self.assertIn("distance=25", urls[1])


class LinkedInApifyScrapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.user = db.create_user(f"liuser_{id(cls)}", password_hash="x", display_name="LI")

    @classmethod
    def tearDownClass(cls):
        db.delete_user(cls.user["id"])
        shutil.rmtree(_TMP, ignore_errors=True)

    def _job(self, job_id):
        return db.get_job_by_id(job_id, self.user["id"])

    def test_bebity_first_with_search_urls_and_apply_link_stored(self):
        items = {BEBITY: [_bebity_item(id="4500000001"),
                          _bebity_item(id="4500000002", applyType="EASY_APPLY",
                                       applyUrl="https://at.linkedin.com/jobs/view/x-4500000002",
                                       jobUrl="https://at.linkedin.com/jobs/view/x-4500000002")]}
        result, client = _run_scrape(self.user, items)
        self.assertTrue(result["success"], result)
        self.assertEqual([actor for actor, _ in client.calls], [BEBITY])
        run_input = client.calls[0][1]
        self.assertEqual(len(run_input["startUrls"]), 2)
        self.assertTrue(all(u["url"].startswith("https://www.linkedin.com/jobs/search/") for u in run_input["startUrls"]))
        self.assertEqual(run_input["maxRowsPerUrl"], 9)
        external = self._job("li_4500000001")
        self.assertEqual(external["apply_type"], "external")
        self.assertEqual(external["apply_url"], "https://www.accenture.com/at-de/careers/jobdetails?id=R00350")
        easy = self._job("li_4500000002")
        self.assertEqual(easy["apply_type"], "easy_apply")
        self.assertIsNone(easy.get("apply_url"))

    def test_bebity_failure_falls_back_to_legacy_actor(self):
        items = {LEGACY: [_legacy_item(id="4500000003")]}
        result, client = _run_scrape(self.user, items, failing=[BEBITY])
        self.assertTrue(result["success"], result)
        self.assertEqual([actor for actor, _ in client.calls], [BEBITY, LEGACY])
        self.assertEqual(client.calls[1][1]["count"], 9)
        job = self._job("li_4500000003")
        self.assertEqual(job["title"], "Python Developer")
        self.assertNotIn("apply_url", job)

    def test_bebity_empty_falls_back_to_legacy_actor(self):
        items = {BEBITY: [], LEGACY: [_legacy_item(id="4500000004")]}
        result, client = _run_scrape(self.user, items)
        self.assertTrue(result["success"], result)
        self.assertEqual([actor for actor, _ in client.calls], [BEBITY, LEGACY])
        self.assertIsNotNone(self._job("li_4500000004"))

    def test_same_job_under_a_new_url_is_not_analysed_again(self):
        first = _bebity_item(id="4500000005")
        result, client = _run_scrape(self.user, {BEBITY: [first]})
        self.assertTrue(result["success"], result)
        self.assertEqual(len(client.ai_calls), 1)
        stored = self._job("li_4500000005")
        self.assertEqual(stored["match_score"], 50)

        again = _bebity_item(id="4500000005", jobUrl=first["jobUrl"] + "&position=7&pageNum=0&refId=abc")
        self.assertNotEqual(again["jobUrl"], first["jobUrl"])
        result, client = _run_scrape(self.user, {BEBITY: [again]})
        self.assertEqual(client.ai_calls, [])
        self.assertEqual(result["state"], "empty")
        kept = self._job("li_4500000005")
        self.assertEqual(kept["match_score"], 50)
        self.assertEqual(kept["job_url"], first["jobUrl"])
        self.assertTrue(kept["last_seen"] >= stored["last_seen"])

    def test_changed_description_under_a_new_url_updates_the_same_job(self):
        first = _bebity_item(id="4500000006")
        _run_scrape(self.user, {BEBITY: [first]})
        stored = self._job("li_4500000006")

        changed = _bebity_item(id="4500000006", description="Completely new text for this role. " * 15,
                               jobUrl=first["jobUrl"] + "&position=3&pageNum=1&refId=xyz")
        result, client = _run_scrape(self.user, {BEBITY: [changed]})
        self.assertTrue(result["success"], result)
        self.assertEqual(len(client.ai_calls), 1)
        updated = self._job("li_4500000006")
        self.assertEqual(updated["id"], "li_4500000006")
        self.assertEqual(updated["first_seen"], stored["first_seen"])
        self.assertIn("Completely new text", updated["raw_description"])
        with db.get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND id=?",
                                 (self.user["id"], "li_4500000006")).fetchone()[0]
        self.assertEqual(count, 1)

    def test_both_actors_failing_is_reported(self):
        result, client = _run_scrape(self.user, {}, failing=[BEBITY, LEGACY])
        self.assertFalse(result["success"])
        self.assertEqual(len(result["errors"]), 2)
        self.assertIn(BEBITY, result["errors"][0])

    def test_both_actors_empty_is_not_an_error(self):
        result, client = _run_scrape(self.user, {})
        self.assertTrue(result["success"])
        self.assertEqual(result["state"], "empty")


class ApplyLinkSurvivesRescrapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.user = db.create_user(f"liuser2_{id(cls)}", password_hash="x", display_name="LI2")

    @classmethod
    def tearDownClass(cls):
        db.delete_user(cls.user["id"])

    def _base(self, **extra):
        job = {"id": "li_4600000001", "job_url": "https://at.linkedin.com/jobs/view/y-4600000001?a=1",
               "title": "T", "company": "C", "description": "d", "date_scraped": "2026-10-12", "source": "LinkedIn (Apify)"}
        job.update(extra)
        return job

    def test_missing_link_does_not_erase_an_earlier_one(self):
        link = "https://careers.example.com/job/1"
        db.upsert_job(self._base(apply_type="external", apply_url=link), user_id=self.user["id"])
        for later in ({}, {"apply_type": None, "apply_url": None}, {"apply_type": "external", "apply_url": ""},
                      {"apply_type": "external", "apply_url": float("nan")}):
            db.upsert_job(self._base(**later), user_id=self.user["id"])
            job = db.get_job_by_id("li_4600000001", self.user["id"])
            self.assertEqual(job["apply_url"], link, later)
            self.assertEqual(job["apply_type"], "external", later)

    def test_a_new_link_replaces_the_old_one(self):
        db.upsert_job(self._base(id="li_4600000002", job_url="https://at.linkedin.com/jobs/view/z-4600000002",
                                 apply_type="external", apply_url="https://old.example.com/1"), user_id=self.user["id"])
        db.upsert_job(self._base(id="li_4600000002", job_url="https://at.linkedin.com/jobs/view/z-4600000002",
                                 apply_type="external", apply_url="https://new.example.com/2"), user_id=self.user["id"])
        job = db.get_job_by_id("li_4600000002", self.user["id"])
        self.assertEqual(job["apply_url"], "https://new.example.com/2")


if __name__ == "__main__":
    unittest.main()
