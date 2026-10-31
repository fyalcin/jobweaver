"""Read-only demo mode: the server refuses changes, and model calls and scrapes refuse to run."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from starlette.requests import Request
from starlette.responses import Response

from jobweaver import demo_mode
from jobweaver import generators
from jobweaver import scrapers
from jobweaver import server

ON = {"JOBWEAVER_DEMO": "1"}


def guard(method, path):
    request = Request({'type': 'http', 'method': method, 'path': path, 'scheme': 'http',
                       'headers': [(b'host', b'localhost')], 'query_string': b''})

    async def call_next(_):
        return Response('passed')
    response = asyncio.run(server.demo_mode_guard(request, call_next))
    return 'passed' if response.status_code == 200 else response


class GuardTest(unittest.TestCase):
    def test_off_by_default_everything_passes(self):
        with patch.dict(os.environ, {"JOBWEAVER_DEMO": ""}):
            self.assertEqual(guard("POST", "/api/scrape"), "passed")
            self.assertEqual(server.demo_status(), {"demo": False})

    def test_reads_and_sign_in_pass(self):
        with patch.dict(os.environ, ON):
            for method, path in (("GET", "/api/jobs"), ("POST", "/api/auth/login"), ("POST", "/api/auth/logout"),
                                 ("OPTIONS", "/api/jobs")):
                self.assertEqual(guard(method, path), "passed", (method, path))

    def test_every_change_is_refused(self):
        with patch.dict(os.environ, ON):
            for method, path in (("POST", "/api/scrape"), ("PUT", "/api/jobs/x"), ("DELETE", "/api/jobs/all"),
                                 ("POST", "/api/generate/cv"), ("POST", "/api/fetch-job-url"), ("PUT", "/api/config"),
                                 ("POST", "/api/jobs/manual"), ("PUT", "/api/cv"), ("PUT", "/api/preferences"),
                                 ("DELETE", "/api/auth/login"), ("PUT", "/api/auth/logout")):
                response = guard(method, path)
                self.assertEqual(response.status_code, 403, (method, path))
                self.assertIn(b"read-only demo", response.body)

    def test_status_names_the_demo_sign_in(self):
        with patch.dict(os.environ, ON):
            status = server.demo_status()
        self.assertEqual((status["demo"], status["username"], status["password"]), (True, "demo", "demo"))


class SecondLayerTest(unittest.TestCase):
    def test_model_calls_refuse(self):
        with patch.dict(os.environ, ON), patch("requests.post") as post:
            with self.assertRaises(demo_mode.DemoModeError):
                generators.run_ai_prompt("Hi", model_name="custom/m")
        post.assert_not_called()

    def test_scrapes_refuse(self):
        with patch.dict(os.environ, ON):
            with self.assertRaises(demo_mode.DemoModeError):
                scrapers.scrape_new_jobs(scrapers.ScrapeParams(source="company-feeds"), user={"id": 1})

    def test_daily_run_does_nothing(self):
        from jobweaver import daily_scraper
        with patch.dict(os.environ, ON), patch("jobweaver.db.list_users") as users:
            daily_scraper.run_daily_scraping()
        users.assert_not_called()

    def test_model_list_does_not_contact_providers(self):
        with patch.dict(os.environ, ON), patch("urllib.request.urlopen") as external, patch("jobweaver.server.list_custom_models") as custom:
            self.assertEqual(server.get_openrouter_models()["models"][0]["id"], "demo/prepared-example")
        external.assert_not_called()
        custom.assert_not_called()


if __name__ == "__main__":
    unittest.main()
