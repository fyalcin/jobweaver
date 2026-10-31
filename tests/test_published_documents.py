"""GET /api/jobs/{id}/published-documents: links only, nothing created (the MCP server's documents route)."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from jobweaver import db
from jobweaver import server


class PublishedDocumentsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous = db.DB_PATH
        self.addCleanup(db.set_db_path, previous)
        db.set_db_path(os.path.join(self.temp.name, "synthetic.db"))
        db.init_db()
        self.user = {"id": 1, "username": "synthetic"}
        db.upsert_job({"id": "li_1", "company": "Acme", "job_url": "https://example.invalid/1"}, user_id=1)
        self.outputs = os.path.join(self.temp.name, "outputs")
        patcher = patch("jobweaver.server.user_outputs_dir", return_value=self.outputs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_documents_creates_nothing(self):
        result = server.get_published_documents("li_1", user=self.user)
        self.assertEqual((result["cv_url"], result["letter_url"], result["finalized"]), (None, None, False))
        self.assertFalse(os.path.exists(self.outputs))

    def test_finalized_set_uses_the_publication_record(self):
        folder = os.path.join(self.outputs, f"{server._make_company_safe('Acme')}_li_1")
        os.makedirs(folder)
        open(os.path.join(folder, "CV-Acme.pdf"), "wb").close()
        with open(os.path.join(folder, "publication.json"), "w") as stream:
            json.dump({"cv_url": "/api/download/x/revisions/r2/CV-Acme.pdf", "revision": "r2"}, stream)
        result = server.get_published_documents("li_1", user=self.user)
        self.assertEqual(result["cv_url"], "/api/download/x/revisions/r2/CV-Acme.pdf")
        self.assertTrue(result["finalized"])
        self.assertIsNone(result["letter_url"])

    def test_summaries_carry_list_fields_only(self):
        db.upsert_job({"id": "li_2", "company": "Beta", "job_url": "https://example.invalid/2", "title": "T",
                       "raw_description": "Long text", "match_score": 70}, user_id=1)
        with patch("jobweaver.server.load_cv_text", return_value="CV"), patch("jobweaver.server._effective_ai_model", return_value="m"):
            summaries = {s["id"]: s for s in server.get_job_summaries(user=self.user)}
        self.assertEqual(summaries["li_2"]["match_score"], 70)
        self.assertNotIn("raw_description", summaries["li_2"])
        self.assertIn("state", summaries["li_2"]["eligibility"])

    def test_summaries_route_is_not_taken_for_a_job_id(self):
        paths = [route.path for route in server.app.routes]
        self.assertLess(paths.index("/api/jobs/summaries"), paths.index("/api/jobs/{job_id}"))

    def test_unknown_job_is_404(self):
        with self.assertRaises(HTTPException) as caught:
            server.get_published_documents("nope", user=self.user)
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
