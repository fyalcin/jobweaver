from model_transport_fixture import inline_transport
"""Models from any OpenAI-compatible endpoint (`custom/<model>`): Ollama, LM Studio, vLLM, llama.cpp, hosted APIs."""
import json
import os
import unittest
from unittest.mock import patch

import generators as g

SCHEMA = {"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "object"}}}
ENV = {"CUSTOM_MODEL_BASE_URL": "http://127.0.0.1:11434/v1/", "CUSTOM_MODEL_API_KEY": ""}


class Response:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload or {}
        self.ok = status < 400
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            error = RuntimeError(f"HTTP {self.status_code}")
            error.response = self
            raise error


def answer(content, finish="stop"):
    return Response(200, {"choices": [{"message": {"content": content}, "finish_reason": finish}]})


class RoutingTest(unittest.TestCase):
    def test_prefix_and_cheapest_routing(self):
        self.assertTrue(g.is_custom_model("custom/llama3.1:8b"))
        self.assertFalse(g.is_custom_model("openai/gpt-5-mini"))
        self.assertEqual(g.apply_route_cheapest("custom/qwen3", True), "custom/qwen3")

    def test_run_ai_prompt_uses_the_endpoint_not_openrouter(self):
        with patch.dict(os.environ, ENV), patch("requests.post", return_value=answer("Hello")) as post:
            self.assertEqual(g.run_ai_prompt("Hi", model_name="custom/llama3.1:8b"), "Hello")
        url = post.call_args.args[0]
        body = post.call_args.kwargs["json"]
        self.assertEqual(url, "http://127.0.0.1:11434/v1/chat/completions")
        self.assertEqual(body["model"], "llama3.1:8b")
        self.assertNotIn("provider", body)    # OpenRouter-only parameters are not sent
        self.assertNotIn("reasoning", body)
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])  # no key configured

    def test_model_ids_with_slashes_keep_them(self):
        with patch.dict(os.environ, ENV), patch("requests.post", return_value=answer("ok")) as post:
            g.run_ai_prompt("Hi", model_name="custom/meta-llama/Llama-3.1-8B-Instruct")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "meta-llama/Llama-3.1-8B-Instruct")

    def test_api_key_is_sent_when_set(self):
        with patch.dict(os.environ, {**ENV, "CUSTOM_MODEL_API_KEY": "secret"}), \
             patch("requests.post", return_value=answer("ok")) as post:
            g.run_ai_prompt("Hi", model_name="custom/m")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer secret")

    def test_missing_base_url_is_a_clear_error_without_retries(self):
        with patch.dict(os.environ, {"CUSTOM_MODEL_BASE_URL": ""}), patch("requests.post") as post:
            with self.assertRaisesRegex(ValueError, "CUSTOM_MODEL_BASE_URL"):
                g.run_ai_prompt("Hi", model_name="custom/m")
        post.assert_not_called()


class CompatibilityTest(unittest.TestCase):
    def test_schema_is_requested_and_think_blocks_and_fences_are_removed(self):
        reply = answer('<think>Let me reason…</think>\n```json\n{"a": 1}\n```')
        with patch.dict(os.environ, ENV), patch("requests.post", return_value=reply) as post:
            text = g.run_ai_prompt("Hi", model_name="custom/qwen3", response_format=SCHEMA)
        self.assertEqual(json.loads(text), {"a": 1})
        self.assertEqual(post.call_args.kwargs["json"]["response_format"], SCHEMA)

    def test_server_without_structured_output_is_asked_again_without_schema(self):
        refused = Response(400, {"error": {"message": "response_format json_schema is not supported"}})
        with patch.dict(os.environ, ENV), patch("requests.post", side_effect=[refused, answer('{"a": 1}')]) as post:
            text = g.run_ai_prompt("Hi", model_name="custom/m", response_format=SCHEMA)
        self.assertEqual(json.loads(text), {"a": 1})
        self.assertNotIn("response_format", post.call_args_list[1].kwargs["json"])
        # the schema request moves into the prompt
        self.assertIn("JSON Schema", post.call_args_list[1].kwargs["json"]["messages"][0]["content"])

    def test_max_tokens_refusal_switches_to_max_completion_tokens(self):
        refused = Response(400, {"error": {"message": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."}})
        with patch.dict(os.environ, ENV), patch("requests.post", side_effect=[refused, answer("ok")]) as post:
            self.assertEqual(g.run_ai_prompt("Hi", model_name="custom/gpt-5-mini"), "ok")
        second = post.call_args_list[1].kwargs["json"]
        self.assertNotIn("max_tokens", second)
        self.assertEqual(second["max_completion_tokens"], g.MAX_OUTPUT_TOKENS)

    def test_other_errors_carry_the_server_message(self):
        refused = Response(404, {"error": {"message": "model 'nope' not found"}})
        with patch.dict(os.environ, ENV), patch("requests.post", return_value=refused):
            with self.assertRaisesRegex(RuntimeError, "model 'nope' not found"):
                g.run_ai_prompt("Hi", model_name="custom/nope")

    def test_truncation_is_reported(self):
        with patch.dict(os.environ, ENV), patch("requests.post", return_value=answer("partial", finish="length")):
            with self.assertRaises(g.AITruncatedError):
                g.custom_model_api("Hi", "custom/m")


class ModelListTest(unittest.TestCase):
    def test_lists_endpoint_models_with_prefix(self):
        listing = Response(200, {"data": [{"id": "llama3.1:8b"}, {"id": "qwen3:14b"}]})
        with patch.dict(os.environ, ENV), patch("requests.get", return_value=listing) as get:
            models = g.list_custom_models()
        self.assertEqual([m["id"] for m in models], ["custom/llama3.1:8b", "custom/qwen3:14b"])
        self.assertEqual(get.call_args.args[0], "http://127.0.0.1:11434/v1/models")

    def test_unreachable_or_unset_endpoint_lists_nothing(self):
        with patch.dict(os.environ, {"CUSTOM_MODEL_BASE_URL": ""}):
            self.assertEqual(g.list_custom_models(), [])
        with patch.dict(os.environ, ENV), patch("requests.get", side_effect=ConnectionError("down")):
            self.assertEqual(g.list_custom_models(), [])


class OpenRouterMessageTest(unittest.TestCase):
    def test_missing_openrouter_key_names_the_alternative(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "custom/"):
                g.openrouter_api("Hi", "z-ai/glm-5.3-flash")



class SettingsModelListTest(unittest.TestCase):
    def test_custom_models_show_even_when_openrouter_is_unreachable(self):
        import server
        with patch("urllib.request.urlopen", side_effect=OSError("offline")), \
             patch("server.list_custom_models", return_value=[{"id": "custom/llama3.1:8b", "name": "x", "context_length": None}]):
            result = server.get_openrouter_models()
        self.assertTrue(result["success"])
        self.assertEqual([m["id"] for m in result["models"]], ["custom/llama3.1:8b"])

    def test_nothing_reachable_reports_the_error(self):
        import server
        with patch("urllib.request.urlopen", side_effect=OSError("offline")), \
             patch("server.list_custom_models", return_value=[]):
            result = server.get_openrouter_models()
        self.assertFalse(result["success"])
        self.assertIn("offline", result["error"])


if __name__ == "__main__":
    unittest.main()


def setUpModule():
    global _transport_fixture
    _transport_fixture = inline_transport()
    _transport_fixture.start()


def tearDownModule():
    _transport_fixture.stop()
