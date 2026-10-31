from model_transport_fixture import inline_transport
import json
import unittest
from unittest import mock

from jobweaver import generators
from jobweaver import job_policy


class RoutingTest(unittest.TestCase):
    def test_floor_becomes_price_sort_without_flex(self):
        self.assertEqual(generators._routing("z-ai/glm-5.3-flash:floor", None),
                         ("z-ai/glm-5.3-flash", {"sort": "price"}))

    def test_structured_output_requires_supporting_provider(self):
        self.assertEqual(generators._routing("m", {"type": "json_schema"}), ("m", {"require_parameters": True}))
        self.assertEqual(generators._routing("m", None), ("m", {}))


class AnalysisSchemaTest(unittest.TestCase):
    def test_schema_is_strict_and_self_contained(self):
        fmt = job_policy.analysis_response_format(True, False)
        schema = fmt["json_schema"]["schema"]
        self.assertTrue(fmt["json_schema"]["strict"])
        self.assertNotIn("$ref", json.dumps(schema))
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("match_score", schema["properties"])
        self.assertEqual(schema["properties"]["match_checks"]["type"], "array")
        self.assertNotIn("tier", schema["properties"]["match_analysis"]["properties"])
        self.assertNotIn("grounding_issues", schema["properties"])
        point = schema["properties"]["match_analysis"]["properties"]["strengths"]["items"]
        self.assertEqual(point["required"], ["title", "detail"])
        self.assertFalse(point["additionalProperties"])

    def test_without_cv_no_match_fields_and_cleanup_optional(self):
        props = job_policy.analysis_response_format(False, True)["json_schema"]["schema"]["properties"]
        self.assertNotIn("match_score", props)
        self.assertIn("cleaned_description", props)
        self.assertNotIn("cleaned_description",
                         job_policy.analysis_response_format(True, False)["json_schema"]["schema"]["properties"])


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.ok = status, body, status < 400

    def json(self):
        return self._body


class SchemaFallbackTest(unittest.TestCase):
    def test_unavailable_structured_output_retries_once_without_schema(self):
        good = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "provider": "X"}
        for status in (404, 429):
            sent, replies = [], [_Resp(status, {}), _Resp(200, good)]

            def post(url, **kwargs):
                sent.append(json.loads(json.dumps(kwargs["json"])))  # copy: the payload is reused
                return replies.pop(0)
            with self.subTest(status=status), mock.patch.dict("os.environ", OPENROUTER_API_KEY="k"), \
                    mock.patch("requests.post", side_effect=post):
                out = generators.openrouter_api("p", "m:floor", response_format={"type": "json_schema"})
            self.assertEqual(out, "{}")
            first, second = sent
            self.assertIn("response_format", first)
            self.assertNotIn("response_format", second)
            self.assertEqual(second["provider"], {"sort": "price"})

    def test_plain_request_does_not_retry(self):
        with mock.patch.dict("os.environ", OPENROUTER_API_KEY="k"), \
                mock.patch("requests.post", return_value=_Resp(429, {"error": {"message": "busy"}})) as post, \
                self.assertRaises(RuntimeError):
            generators.openrouter_api("p", "m")
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()


def setUpModule():
    global _transport_fixture
    _transport_fixture = inline_transport()
    _transport_fixture.start()


def tearDownModule():
    _transport_fixture.stop()
