import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import db

# Point db at a throwaway SQLite file BEFORE importing scrapers.
_TMP = tempfile.mkdtemp(prefix="gj-ka-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

import scrapers  # noqa: E402


def _fresh_iso(hours_ago=2):
    return (datetime.now().astimezone() - timedelta(hours=hours_ago)).isoformat()


def _item(**overrides):
    """A blackfalcondata/karriere-at-scraper record, minus empty fields
    (the actor is called with excludeEmptyFields: true). Default postedDate
    is fresh so the age filter (default 48h in _run_scrape) keeps it."""
    item = {
        "jobId": "10031332",
        "title": "Top-Verkäufer/in (m/w/d)",
        "company": "Benussi GmbH",
        "location": "Wien 11. Bezirk (Simmering)",
        "description": "Wir suchen ein Verkaufstalent mit Erfahrung. " * 20,
        "salaryText": "ab 5.000 € monatlich",
        "salaryMin": 5000,
        "salaryPeriod": "MONTH",
        "postedDate": _fresh_iso(),
        "employmentType": "Vollzeit",
        "url": "https://www.karriere.at/jobs/10031332",
    }
    for key, value in overrides.items():
        if value is None:
            item.pop(key, None)
        else:
            item[key] = value
    return item


class _FakeDataset:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        return iter(list(self._items))


class _FakeActor:
    def __init__(self, client):
        self._client = client

    def call(self, run_input=None):
        self._client.run_inputs.append(run_input or {})
        return {"defaultDatasetId": "ds-1"}


class _FakeApifyClient:
    def __init__(self, token):
        self.token = token
        self.run_inputs = []
        self.items = []
        self.actor_id = None

    def actor(self, actor_id):
        self.actor_id = actor_id
        return _FakeActor(self)

    def dataset(self, dataset_id):
        return _FakeDataset(self.items)


def _ai_stub(description, cv_text=None, model_name=None, denoise=True):
    return {
        "german_level": "none", "requires_german": False,
        "salary": "AI Salary", "salary_yearly": None,
        "skills": "x", "summary": "s", "company_contact": None,
        "match_score": 50, "description": description,
    }


def _run_scrape(user, items, hours_old=48, results_limit=10, ai_yearly=None):
    """Run scrape_new_jobs for karriere-apify against a fake Apify client.

    The branch constructs its own ApifyClient(token), so the patch swaps in a
    factory that wires the fake to the prepared items and hands it back.
    """

    def ai(description, cv_text=None, model_name=None, denoise=True):
        payload = _ai_stub(description)
        payload["salary_yearly"] = ai_yearly
        return payload

    holder = {}

    def _client_factory(token):
        client = _FakeApifyClient(token)
        client.items = items
        holder["client"] = client
        return client

    with mock.patch.dict(os.environ, {"APIFY_API_TOKEN": "token-test"}), \
         mock.patch("apify_client.ApifyClient", _client_factory), \
         mock.patch.object(scrapers, "process_job_with_ai", side_effect=ai):
        result = scrapers.scrape_new_jobs(
            scrapers.ScrapeParams(
                results_limit=results_limit, hours_old=hours_old,
                keywords="Verkäufer", source="karriere-apify",
            ),
            cv_text="cv", user=user,
        )
    return result, holder["client"]


class KarriereApifyActorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.user = db.create_user(f"kauser_{id(cls)}", password_hash="x", display_name="KA")
        cls.username = cls.user["username"]

    @classmethod
    def tearDownClass(cls):
        db.delete_user(cls.user["id"])
        shutil.rmtree(_TMP, ignore_errors=True)

    def _job(self, job_id):
        return db.get_job_by_id(job_id, self.user["id"])

    def test_actor_and_incremental_input(self):
        result, client = _run_scrape(self.user, [_item()], hours_old=24, results_limit=7)
        self.assertEqual(client.actor_id, "blackfalcondata/karriere-at-scraper")
        run_input = client.run_inputs[0]
        self.assertTrue(run_input["incrementalMode"])
        self.assertTrue(run_input["includeDetails"])
        self.assertEqual(run_input["descriptionFormat"], "text")
        self.assertTrue(run_input["excludeEmptyFields"])
        self.assertEqual(run_input["query"], "Verkäufer")
        self.assertEqual(run_input["maxResults"], 7)
        self.assertEqual(run_input["location"], "wien-und-umgebung")
        self.assertEqual(run_input["radius"], "10")
        # stateKey is per user + keyword + region so two users never share state
        self.assertEqual(
            run_input["stateKey"],
            f"gj-{self.username}-karriere-wien-und-umgebung-Verkäufer",
        )

    def test_mapping_structured_salary_and_stable_id(self):
        posted = _fresh_iso(hours_ago=3)
        _run_scrape(self.user, [_item(
            jobId="10055555", url="https://www.karriere.at/jobs/10055555", postedDate=posted)])
        job = self._job("karriere_10055555")
        self.assertIsNotNone(job)
        self.assertEqual(job["job_url"], "https://www.karriere.at/jobs/10055555")
        self.assertEqual(job["company"], "Benussi GmbH")
        self.assertEqual(job["salary"], "ab 5.000 € monatlich")
        self.assertEqual(job["salary_yearly"], 70_000)  # 5.000 MONTH x 14
        self.assertEqual(job["type"], "Vollzeit")
        self.assertEqual(job["posted_date"], posted)

    def test_id_matches_selenium_derivation(self):
        _run_scrape(self.user, [_item(url="https://www.karriere.at/jobs/7858073", jobId="7858073")])
        self.assertIsNotNone(self._job("karriere_7858073"))

    def test_salary_fallback_from_text(self):
        _run_scrape(self.user, [_item(jobId="10029484", url="https://www.karriere.at/jobs/10029484",
                                      salaryText="ab 40.000 € jährlich",
                                      salaryMin=None, salaryPeriod=None)])
        job = self._job("karriere_10029484")
        self.assertEqual(job["salary_yearly"], 40_000)

    def test_scraper_salary_wins_over_ai(self):
        _run_scrape(self.user, [_item()], ai_yearly=99_999)
        self.assertEqual(self._job("karriere_10031332")["salary_yearly"], 70_000)

    def test_age_filter_drops_stale_listings(self):
        fresh = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
        stale = (datetime.now().astimezone() - timedelta(hours=72)).isoformat()
        _run_scrape(
            self.user,
            [
                _item(jobId="10000001", url="https://www.karriere.at/jobs/10000001", postedDate=fresh),
                _item(jobId="10000002", url="https://www.karriere.at/jobs/10000002", postedDate=stale),
            ],
            hours_old=48,
        )
        self.assertIsNotNone(self._job("karriere_10000001"))
        self.assertIsNone(self._job("karriere_10000002"))

    def test_missing_posted_date_is_kept(self):
        _run_scrape(self.user, [_item(jobId="10000003", url="https://www.karriere.at/jobs/10000003",
                                      postedDate=None)])
        self.assertIsNotNone(self._job("karriere_10000003"))

    def test_db_dedup_blocks_re_emitted_listings(self):
        # Safety net: if the actor's incremental state is lost, it re-emits the
        # full universe — our per-user URL dedup must stop a re-analysis.
        _run_scrape(self.user, [_item()])
        before = self._job("karriere_10031332")
        result, _ = _run_scrape(self.user, [_item()])
        self.assertEqual(result.get("new_jobs_count", 0), 0)
        after = self._job("karriere_10031332")
        self.assertEqual(before["description"], after["description"])


if __name__ == "__main__":
    unittest.main()
