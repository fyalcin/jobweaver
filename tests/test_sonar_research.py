import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import db
from generators import research_company_sonar
from server import app
from fastapi.testclient import TestClient


class TestSonarResearch(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-sonar-test-")
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        db.set_db_path(self.db_path)
        db.init_db()

        self.user = db.create_user("testuser", "password123")
        self.user_id = self.user["id"]
        from server import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"id": self.user_id, "username": "testuser"}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("generators.run_ai_prompt")
    def test_research_company_sonar_prompt_and_model(self, mock_ai_prompt):
        mock_ai_prompt.return_value = "## 1. Overview\nAcme Corp makes widgets."

        result = research_company_sonar(
            company="Acme Corp",
            role_title="Lead Engineer",
            description="We build rockets.",
            model_name="perplexity/sonar"
        )
        self.assertIn("Acme Corp makes widgets", result)
        self.assertTrue(mock_ai_prompt.called)
        prompt = mock_ai_prompt.call_args[0][0]
        self.assertIn("Acme Corp", prompt)
        self.assertIn("Lead Engineer", prompt)
        self.assertIn("We build rockets", prompt)
        self.assertEqual(mock_ai_prompt.call_args[1].get("model_name"), "perplexity/sonar")

    def test_research_company_sonar_empty_company_raises(self):
        with self.assertRaises(ValueError):
            research_company_sonar(company="   ")


    @patch("server.research_company_sonar")
    def test_research_endpoint_persists_to_db(self, mock_sonar):
        mock_sonar.return_value = "## 1. Overview\nCloud-native logistics software."

        # Insert a job
        job_id = "test_job_1"
        db.upsert_job({
            "id": job_id,
            "title": "Backend Dev",
            "company": "LogisticsTech",
            "description": "Python, Go, Kubernetes",
            "job_url": "https://example.com/job1"
        }, user_id=self.user_id)

        # Call POST /api/jobs/{job_id}/research
        resp = self.client.post(f"/api/jobs/{job_id}/research", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["company_research"], "## 1. Overview\nCloud-native logistics software.")
        self.assertIsNotNone(data["company_research_updated_at"])

        # Check DB directly
        stored = db.get_job_by_id(job_id, self.user_id)
        self.assertEqual(stored["company_research"], "## 1. Overview\nCloud-native logistics software.")
        self.assertIsNotNone(stored["company_research_updated_at"])

        # Check GET /api/jobs/{job_id}
        get_resp = self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["job"]["company_research"], "## 1. Overview\nCloud-native logistics software.")

        # Test PUT /api/jobs/{job_id} to edit research notes
        put_resp = self.client.put(f"/api/jobs/{job_id}", json={
            "company_research": "Edited research notes: specializes in Vienna logistics.",
            "use_research_in_docs": False
        })
        self.assertEqual(put_resp.status_code, 200)
        updated_stored = db.get_job_by_id(job_id, self.user_id)
        self.assertEqual(updated_stored["company_research"], "Edited research notes: specializes in Vienna logistics.")
        self.assertFalse(updated_stored["use_research_in_docs"])


if __name__ == "__main__":
    unittest.main()
