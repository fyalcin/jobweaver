import os
import tempfile
import unittest
from unittest import mock

from jobweaver import db

# Point db at a throwaway SQLite file BEFORE importing server (server runs
# db.init_db() at import time).
_TMP = tempfile.mkdtemp(prefix="gj-rp-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

from jobweaver import server  # noqa: E402


def _stub_ai(description, cv_text=None, model_name=None, denoise=True):
    return {
        "german_level": "none",
        "requires_german": False,
        "salary": "Not Specified",
        "skills": "Retail, Sales",
        "summary": "Stub summary.",
        "company_contact": None,
        "match_score": 42,
        "description": description,
    }


def setUpModule():
    # Discovery imports every module first; point at this module's DB while it runs.
    db.set_db_path(os.path.join(_TMP, "test.db"))


def tearDownModule():
    db.set_db_path(os.path.join(db.DATA_DIR, "jobweaver.db"))  # The runner's disposable default.


class ReprocessBackgroundTest(unittest.TestCase):
    """_run_reprocess_bg must poll its task row with the owning user_id.

    Regression: the multi-user refactor made db.async_task_get_reprocess
    require user_id, but the background loop still called it without one —
    every reprocess task died with a TypeError on the first iteration and
    stayed 'running' forever, wedging the UI's Processing Queue on a zombie
    task.
    """

    def setUp(self):
        db.init_db()
        uname = f"rpuser_{id(self)}"
        self.user = db.create_user(uname, password_hash="x", display_name="RP")
        db.upsert_job(
            {
                "id": "li_regress_1",
                "job_url": "https://example.com/job/r1",
                "title": "Front Office Manager",
                "company": "Example Hotels",
                "date_scraped": "2026-09-01",
                "source": "LinkedIn (Browser)",
                "status": "new",
                "processed": 0,
                "description": "A long job description " * 50,
            },
            user_id=self.user["id"],
        )

    def tearDown(self):
        db.delete_user(self.user["id"])

    def test_reprocess_bg_completes_and_marks_jobs_processed(self):
        task_id = "rp-regress-task"
        db.async_task_create(task_id, "reprocess", total=1, user_id=self.user["id"])
        with mock.patch.object(server._scrapers, "process_job_with_ai", side_effect=_stub_ai):
            server._run_reprocess_bg(task_id, {"id": self.user["id"], "username": self.user["username"]})
        row = db.async_task_get_reprocess(task_id, self.user["id"])
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["processed"], 1)
        self.assertEqual(row["failed"], 0)
        job = db.get_job_by_id("li_regress_1", self.user["id"])
        self.assertEqual(job["processed"], 1)
        self.assertEqual(job["match_score"], 42)

    def test_reprocess_bg_survives_ai_failure(self):
        task_id = "rp-regress-task-fail"
        db.async_task_create(task_id, "reprocess", total=1, user_id=self.user["id"])
        with mock.patch.object(server._scrapers, "process_job_with_ai", side_effect=ValueError("boom")):
            server._run_reprocess_bg(task_id, {"id": self.user["id"], "username": self.user["username"]})
        row = db.async_task_get_reprocess(task_id, self.user["id"])
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["failed"], 1)
        job = db.get_job_by_id("li_regress_1", self.user["id"])
        self.assertEqual(job["processed"], 0)
        self.assertEqual(job['analysis_state'], 'failed')
        self.assertEqual(job['analysis_error'], 'boom')

    def _add_job(self, jid, description, date="2026-09-01", **extra):
        db.upsert_job({"id": jid, "job_url": f"https://example.com/job/{jid}", "title": jid, "company": "X",
                       "date_scraped": date, "source": "LinkedIn (Browser)", "status": "new", "processed": 0,
                       "description": description, **extra}, user_id=self.user["id"])

    def _user(self):
        return {"id": self.user["id"], "username": self.user["username"]}

    def test_reprocess_runs_jobs_in_parallel(self):
        import threading, time
        for i in range(6):
            self._add_job(f"li_par_{i}", "Description " * 20)
        active, peak, lock = [0], [0], threading.Lock()
        def slow(*args, **kwargs):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return _stub_ai(*args, **kwargs)
        db.async_task_create("rp-par", "reprocess", total=7, user_id=self.user["id"])
        with mock.patch.object(server._scrapers, "process_job_with_ai", side_effect=slow):
            server._run_reprocess_bg("rp-par", self._user())
        row = db.async_task_get_reprocess("rp-par", self.user["id"])
        self.assertEqual((row["status"], row["processed"], row["failed"]), ("completed", 7, 0))
        self.assertGreater(peak[0], 1)

    def test_job_without_description_is_skipped_and_leaves_queue(self):
        self._add_job("ds_empty", "")
        db.async_task_create("rp-skip", "reprocess", total=2, user_id=self.user["id"])
        with mock.patch.object(server._scrapers, "process_job_with_ai", side_effect=_stub_ai) as model:
            server._run_reprocess_bg("rp-skip", self._user())
        self.assertEqual(model.call_count, 1)
        job = db.get_job_by_id("ds_empty", self.user["id"])
        self.assertEqual(job["analysis_state"], "skipped")
        ids = [j["id"] for j in db.load_unprocessed_jobs(self.user["id"])]
        self.assertNotIn("ds_empty", ids)
        self.assertEqual(db.get_unprocessed_count(self.user["id"]), 0)

    def test_daily_retry_only_recent_failures_and_capped(self):
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y-%m-%d")
        old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        db.update_job_fields("li_regress_1", user_id=self.user["id"], analysis_state="failed")
        for jid, date in (("li_recent_a", today), ("li_recent_b", today), ("li_old", old)):
            self._add_job(jid, "Description " * 20, date=date, analysis_state="failed")
        self._add_job("li_pending", "Description " * 20, date=today, analysis_state="pending")
        with mock.patch.object(server._scrapers, "process_job_with_ai", side_effect=_stub_ai) as model:
            ok, failed = server._scrapers.retry_failed_analyses(self._user(), "CV", "m", days=3, limit=1)
        self.assertEqual((ok, failed, model.call_count), (1, 0, 1))
        with mock.patch.object(server._scrapers, "process_job_with_ai", side_effect=ValueError("still bad")):
            ok, failed = server._scrapers.retry_failed_analyses(self._user(), "CV", "m", days=3, limit=15)
        self.assertEqual((ok, failed), (0, 1))
        self.assertEqual(db.get_job_by_id("li_old", self.user["id"])["analysis_state"], "failed")
        self.assertEqual(db.get_job_by_id("li_pending", self.user["id"])["processed"], 0)


if __name__ == "__main__":
    unittest.main()
