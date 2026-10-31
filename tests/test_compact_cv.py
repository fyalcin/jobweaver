import unittest
from unittest.mock import patch
from jobweaver.cv_profiles import PROFILES, profile_compact_template, profile_template
from jobweaver.server import GenerateRequest, BatchGenerateRequest, ManualJobRequest, RefineStartRequest


class TestCompactCvGeneration(unittest.TestCase):
    def test_request_models_compact_defaults(self):
        gen_req = GenerateRequest(job_id="test_1")
        self.assertFalse(gen_req.compact)

        batch_req = BatchGenerateRequest(job_ids=["test_1"])
        self.assertFalse(batch_req.compact)

        manual_req = ManualJobRequest(title="Dev")
        self.assertFalse(manual_req.compact)

        refine_req = RefineStartRequest(job_id="test_1")
        self.assertFalse(refine_req.compact)

    def test_request_models_compact_explicit(self):
        gen_req = GenerateRequest(job_id="test_1", compact=True)
        self.assertTrue(gen_req.compact)

        batch_req = BatchGenerateRequest(job_ids=["test_1"], compact=True)
        self.assertTrue(batch_req.compact)

        manual_req = ManualJobRequest(title="Dev", compact=True)
        self.assertTrue(manual_req.compact)

        refine_req = RefineStartRequest(job_id="test_1", compact=True)
        self.assertTrue(refine_req.compact)


if __name__ == "__main__":
    unittest.main()
