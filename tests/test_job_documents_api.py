import os
import shutil
import tempfile
import unittest
from unittest import mock

from jobweaver import db

_TMP = tempfile.mkdtemp(prefix="gj-job-docs-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

from jobweaver import server  # noqa: E402
from jobweaver import user_assets  # noqa: E402
from pdf_fixture import pdf_bytes
from jobweaver.document_artifacts import record_build


def setUpModule():
    # Discovery imports every module first; point at this module's DB while it runs.
    db.set_db_path(os.path.join(_TMP, "test.db"))
    db.init_db()


def tearDownModule():
    db.set_db_path(os.path.join(db.DATA_DIR, "jobweaver.db"))  # The runner's disposable default.


class JobDocumentsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-job-docs-paths-")
        patcher = mock.patch.multiple(
            user_assets,
            BASE_DIR=self.tmp_dir,
            PROFILES_DIR=os.path.join(self.tmp_dir, "profiles"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

        self.user = {"id": 1, "username": db.DEFAULT_USER_USERNAME}
        self.job = {
            "id": "test_job_101",
            "title": "Integration Engineer",
            "company": "AcmeNanotech",
            "description": "Building nanotech tools.",
            "url": "https://example.com/jobs/101",
        }
        db.upsert_job(self.job, user_id=self.user["id"])

    def test_get_job_documents_empty(self):
        res = server.get_job_documents("test_job_101", user=self.user)
        self.assertTrue(res["success"])
        self.assertFalse(res["has_cv"])
        self.assertFalse(res["has_letter"])
        self.assertEqual(res["cv_tex"], "")
        self.assertEqual(res["cl_tex"], "")
        self.assertEqual(res["cv_images"], [])
        self.assertEqual(res["cl_images"], [])

    def test_compile_job_document_mocked(self):
        draft_dir = os.path.join(user_assets.user_drafts_dir(self.user["username"]), "AcmeNanotech_test_job_101")
        os.makedirs(draft_dir, exist_ok=True)
        pdf_file = os.path.join(draft_dir, "cv_draft_test_job_101.pdf")
        with open(pdf_file, "w") as f:
            f.write("fake pdf")

        req = server.JobDocCompileRequest(
            document_type="cv",
            tex=r"\documentclass{article}\begin{document}Test CV\end{document}",
        )
        with mock.patch("jobweaver.server.compile_latex", return_value=(True, "Success")), \
             mock.patch("jobweaver.server.convert_pdf_to_images", return_value=["cv_img_test_job_101-1.png"]):
            res = server.compile_job_document("test_job_101", req, user=self.user)

        # A mocked success without a validated fresh build cannot be accepted.
        self.assertFalse(res["success"])

    def test_finalize_job_documents_flow(self):
        req = server.JobDocFinalizeRequest(document_type="all")
        draft_dir = os.path.join(user_assets.user_drafts_dir(self.user["username"]), "AcmeNanotech_test_job_101")
        os.makedirs(draft_dir, exist_ok=True)
        with open(os.path.join(draft_dir, "cv_draft_test_job_101.pdf"), "wb") as f:
            f.write(pdf_bytes())
        with open(os.path.join(draft_dir, "cv_test_job_101.tex"), "w") as f:
            f.write("fake tex")
        record_build(os.path.join(draft_dir, "cv_draft_test_job_101.pdf"), 'fake tex', 'latex')

        res = server.finalize_job_documents("test_job_101", req, user=self.user)
        self.assertTrue(res["success"])
        self.assertIsNotNone(res["cv_url"])


if __name__ == "__main__":
    unittest.main()
