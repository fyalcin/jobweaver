import shutil
import tempfile
import unittest

from jobweaver import db


class MultiUserDBTestBase(unittest.TestCase):
    """Base that points db at a temporary SQLite file and initialises it."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-test-")
        self._orig_db_path = db.DB_PATH
        db.set_db_path(__import__("os").path.join(self.tmp_dir, "test.db"))
        db.init_db()
        self.default_user = db.get_user_by_username(db.DEFAULT_USER_USERNAME)
        self.wife = db.create_user("wife", password_hash="x", display_name="Wife")

    def tearDown(self):
        db.set_db_path(self._orig_db_path)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @staticmethod
    def _job(job_id="li_1", url="https://example.com/job/1", **overrides):
        job = {
            "id": job_id,
            "job_url": url,
            "title": "Backend Developer",
            "company": "Example GmbH",
            "date_scraped": "2026-08-31",
            "source": "linkedin-apify",
            "status": "new",
            "processed": 1,
            "match_score": 80,
            "description": "A job description",
        }
        job.update(overrides)
        return job


class TestUserAccounts(MultiUserDBTestBase):
    def test_default_user_bootstrapped(self):
        self.assertIsNotNone(self.default_user)
        self.assertEqual(self.default_user["id"], 1)
        self.assertIsNone(self.default_user["password_hash"])

    def test_duplicate_username_rejected(self):
        with self.assertRaises(ValueError):
            db.create_user("WIFE")  # case-insensitive uniqueness

    def test_get_user_by_username_is_case_insensitive(self):
        self.assertIsNotNone(db.get_user_by_username("WiFe"))

    def test_get_user_by_telegram_chat(self):
        db.update_user_fields(self.wife["id"], telegram_chat_id="12345")
        self.assertEqual(db.get_user_by_telegram_chat("12345")["id"], self.wife["id"])
        self.assertIsNone(db.get_user_by_telegram_chat("99999"))

    def test_update_user_fields_ignores_unknown(self):
        self.assertFalse(db.update_user_fields(self.wife["id"], username="hax"))


class TestJobIsolation(MultiUserDBTestBase):
    def test_upsert_requires_user_id(self):
        with self.assertRaises(ValueError):
            db.upsert_job(self._job())

    def test_same_job_id_and_url_allowed_for_both_users(self):
        db.upsert_job(self._job(), user_id=self.default_user["id"])
        db.upsert_job(self._job(), user_id=self.wife["id"])
        mine = db.get_job_by_id("li_1", self.default_user["id"])
        hers = db.get_job_by_id("li_1", self.wife["id"])
        self.assertIsNotNone(mine)
        self.assertIsNotNone(hers)
        self.assertEqual(len(db.load_jobs(self.default_user["id"])), 1)
        self.assertEqual(len(db.load_jobs(self.wife["id"])), 1)

    def test_same_user_same_url_replaces(self):
        db.upsert_job(self._job(), user_id=self.default_user["id"])
        db.upsert_job(self._job(title="Updated Title"), user_id=self.default_user["id"])
        jobs = db.load_jobs(self.default_user["id"])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs.iloc[0]["title"], "Updated Title")

    def test_get_update_and_delete_are_user_scoped(self):
        db.upsert_job(self._job(), user_id=self.default_user["id"])

        # Cross-user reads fail
        self.assertIsNone(db.get_job_by_id("li_1", self.wife["id"]))

        # Cross-user updates fail
        self.assertFalse(db.update_job_fields("li_1", user_id=self.wife["id"], status="applied"))
        self.assertEqual(db.get_job_by_id("li_1", self.default_user["id"])["status"], "new")

        # Own updates succeed
        self.assertTrue(db.update_job_fields("li_1", user_id=self.default_user["id"], status="applied"))
        self.assertEqual(db.get_job_by_id("li_1", self.default_user["id"])["status"], "applied")

        # Cross-user deletes fail
        db.delete_all_jobs(self.wife["id"])
        self.assertIsNotNone(db.get_job_by_id("li_1", self.default_user["id"]))

    def test_delete_single_job_is_user_scoped(self):
        db.upsert_job(self._job(), user_id=self.default_user["id"])
        # Cross-user delete fails
        self.assertFalse(db.delete_job("li_1", self.wife["id"]))
        self.assertIsNotNone(db.get_job_by_id("li_1", self.default_user["id"]))
        # Own delete works, also for pipeline statuses
        db.update_job_fields("li_1", user_id=self.default_user["id"], status="applied")
        self.assertTrue(db.delete_job("li_1", self.default_user["id"]))
        self.assertIsNone(db.get_job_by_id("li_1", self.default_user["id"]))
        self.assertFalse(db.delete_job("li_1", self.default_user["id"]))

    def test_scoped_counts_and_dates(self):
        db.upsert_job(self._job(), user_id=self.default_user["id"])
        db.upsert_job(
            self._job(job_id="li_2", url="https://example.com/2", date_scraped="2026-08-30"),
            user_id=self.wife["id"],
        )
        self.assertEqual(db.get_unprocessed_count(self.default_user["id"]), 0)
        self.assertEqual(db.load_jobs_by_date(self.wife["id"], "2026-08-30").shape[0], 1)
        self.assertEqual(db.load_jobs_by_date(self.wife["id"], "2026-08-31").shape[0], 0)
        self.assertEqual(db.load_distinct_scrape_dates(self.wife["id"]), ["2026-08-30"])
        self.assertEqual(db.load_distinct_scrape_dates(self.default_user["id"]), ["2026-08-31"])
        self.assertEqual(db.load_job_urls(self.default_user["id"]), {"https://example.com/job/1"})
        self.assertEqual(db.load_job_urls(self.wife["id"]), {"https://example.com/2"})

    def test_merge_row_includes_user_id(self):
        db.upsert_job(self._job(), user_id=self.default_user["id"])
        job = db.get_job_by_id("li_1", self.default_user["id"])
        self.assertEqual(job["user_id"], self.default_user["id"])


class TestTasksAndLogs(MultiUserDBTestBase):
    def test_async_tasks_are_user_scoped(self):
        db.async_task_create("t1", "scrape", user_id=self.default_user["id"])
        self.assertIsNotNone(db.async_task_get_scrape("t1", self.default_user["id"]))
        self.assertIsNone(db.async_task_get_scrape("t1", self.wife["id"]))
        self.assertIsNone(db.async_task_get_latest_running_scrape(self.wife["id"]))
        got = db.async_task_get_latest_running_scrape(self.default_user["id"])
        self.assertEqual(got[0], "t1")

    def test_cancel_running_reprocess_is_user_scoped(self):
        db.async_task_create("t2", "reprocess", user_id=self.default_user["id"])
        db.async_task_cancel_running_reprocess(self.wife["id"])
        self.assertFalse(db.async_task_get_reprocess("t2", self.default_user["id"])["cancelled"])
        db.async_task_cancel_running_reprocess(self.default_user["id"])
        self.assertTrue(db.async_task_get_reprocess("t2", self.default_user["id"])["cancelled"])

    def test_scraping_logs_scoped_with_legacy_visible(self):
        db.add_log("legacy entry")  # user_id NULL → visible to everyone
        db.add_log("my scrape", user_id=self.default_user["id"])
        db.add_log("wife scrape", user_id=self.wife["id"])

        mine = {log["message"] for log in db.get_logs(self.default_user["id"])}
        hers = {log["message"] for log in db.get_logs(self.wife["id"])}
        self.assertIn("my scrape", mine)
        self.assertNotIn("wife scrape", mine)
        self.assertIn("wife scrape", hers)
        self.assertNotIn("my scrape", hers)
        self.assertIn("legacy entry", mine)
        self.assertIn("legacy entry", hers)


class TestLegacyMigration(MultiUserDBTestBase):
    def test_old_single_user_schema_is_migrated(self):
        """A pre-multi-user jobs table (no user_id) is rebuilt with rows assigned to the default user."""
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute("DROP TABLE jobs")
        conn.execute("""
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                job_url TEXT UNIQUE,
                title TEXT, company TEXT, date_scraped TEXT, source TEXT,
                requires_german INTEGER, match_score INTEGER,
                applied INTEGER DEFAULT 0, status TEXT DEFAULT 'new',
                is_one_off INTEGER DEFAULT 0,
                application_date TEXT, application_method TEXT,
                response_status TEXT, company_contact TEXT,
                processed INTEGER DEFAULT 1, data TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO jobs (id, job_url, title, company, date_scraped, source, match_score, processed, data) "
            "VALUES ('old_1', 'https://old.example/1', 'Old Job', 'OldCo', '2026-01-01', 'manual', 77, 1, '{}')"
        )
        conn.commit()
        conn.close()

        db.init_db()
        job = db.get_job_by_id("old_1", self.default_user["id"])
        self.assertIsNotNone(job)
        self.assertEqual(job["title"], "Old Job")
        # Other users still see nothing
        self.assertIsNone(db.get_job_by_id("old_1", self.wife["id"]))


if __name__ == "__main__":
    unittest.main()
