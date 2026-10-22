import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import db
import mark_applied


class MarkAppliedTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-test-")
        self._orig_db_path = db.DB_PATH
        db.set_db_path(os.path.join(self.tmp_dir, "test.db"))
        db.init_db()
        self.user = db.get_user_by_username(db.DEFAULT_USER_USERNAME)

    def tearDown(self):
        db.set_db_path(self._orig_db_path)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _add(self, job_id="li_1", **fields):
        job = {"id": job_id, "job_url": f"https://example.com/{job_id}", "title": "Engineer",
               "company": "Example GmbH", "date_scraped": "2026-10-12", "status": "new", "processed": 1}
        job.update(fields)
        db.upsert_job(job, user_id=self.user["id"])

    def _run(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mark_applied.main(["--user", self.user["username"], *args])
        return code, json.loads(out.getvalue())

    def test_new_job_becomes_applied(self):
        self._add()
        code, res = self._run("--job", "li_1", "--date", "2026-10-12", "--method", "email")
        self.assertEqual((code, res["changed"], res["previous_status"], res["status"]), (0, True, "new", "applied"))
        job = db.get_job_by_id("li_1", self.user["id"])
        self.assertEqual(job["status"], "applied")
        self.assertTrue(job["applied"])
        self.assertEqual(job["application_date"], "2026-10-12")
        self.assertEqual(job["application_method"], "email")

    def test_second_run_changes_nothing(self):
        self._add()
        self._run("--job", "li_1", "--date", "2026-10-12")
        code, res = self._run("--job", "li_1", "--date", "2026-10-14")
        self.assertEqual((code, res["changed"]), (0, False))
        self.assertEqual(db.get_job_by_id("li_1", self.user["id"])["application_date"], "2026-10-12")

    def test_later_status_is_kept(self):
        self._add(status="interview")
        code, res = self._run("--job", "li_1", "--date", "2026-10-12")
        self.assertEqual((code, res["changed"], res["status"]), (0, True, "interview"))
        job = db.get_job_by_id("li_1", self.user["id"])
        self.assertEqual(job["status"], "interview")
        self.assertTrue(job["applied"])

    def test_unknown_job_and_bad_date(self):
        self.assertEqual(self._run("--job", "li_missing")[0], 2)
        self._add()
        code, res = self._run("--job", "li_1", "--date", "12.10.2026")
        self.assertEqual(code, 2)
        self.assertEqual(db.get_job_by_id("li_1", self.user["id"])["status"], "new")


if __name__ == "__main__":
    unittest.main()
