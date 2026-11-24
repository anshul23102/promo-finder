import os
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from promo import screenplay
from promo.export import safe_cell
from promo.llm import Model


class SafetyTest(unittest.TestCase):
    def test_zip_over_limit_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bomb.zip"
            with ZipFile(path, "w") as z:
                z.writestr("episode-1.txt", "x" * 2000)
            old = screenplay.MAX_FILE_BYTES
            screenplay.MAX_FILE_BYTES = 1000
            try:
                with self.assertRaisesRegex(ValueError, "ZIP too large"):
                    screenplay.load_episodes(path)
            finally:
                screenplay.MAX_FILE_BYTES = old

    def test_spreadsheet_formulas_are_neutralised(self):
        self.assertEqual(safe_cell('=HYPERLINK("http://x")'), "'=HYPERLINK(\"http://x\")")
        self.assertEqual(safe_cell("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(safe_cell("Plain text"), "Plain text")
        self.assertEqual(safe_cell(12.5), 12.5)

    def test_typed_key_is_per_model_and_never_touches_the_environment(self):
        os.environ.pop("GEMINI_API_KEY", None)
        with tempfile.TemporaryDirectory() as tmp:
            a = Model("gemini", Path(tmp), key="visitor-a-key")
            with self.assertRaisesRegex(ValueError, "needs GEMINI_API_KEY"):
                Model("gemini", Path(tmp))          # another visitor, no key: must not inherit A's
        self.assertEqual(a.key, "visitor-a-key")
        self.assertNotIn("GEMINI_API_KEY", os.environ)


class EndpointTest(unittest.TestCase):
    def test_visitor_endpoints_must_be_public_https(self):
        from promo.llm import public_https
        for bad in ("http://example.com/v1", "https://127.0.0.1/v1", "https://169.254.169.254/latest",
                    "https://10.0.0.5/v1", "https://localhost:8000/v1", "file:///etc/passwd"):
            with self.assertRaises(ValueError, msg=bad):
                public_https(bad)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            Model("openai-compatible:any", Path(tmp), key="k", base_url="https://192.168.1.10/v1")


if __name__ == "__main__":
    unittest.main()


class RateLimitTest(unittest.TestCase):
    def test_daily_cap_stops_instead_of_sleeping(self):
        import io
        from urllib import error, request
        from unittest import mock
        body = io.BytesIO(b'{"error":{"message":"Rate limit reached for model on tokens per day (TPD): Limit 200000"}}')
        http = error.HTTPError("u", 429, "Too Many Requests", {"retry-after": "7200"}, body)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(request, "urlopen", side_effect=http), \
                mock.patch("time.sleep") as slept:
            m = Model("groq:openai/gpt-oss-120b", Path(tmp), key="k")
            with self.assertRaisesRegex(Exception, "daily limit reached"):
                m.ask("t", "s", "u", {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False})
            self.assertFalse(any(c.args and c.args[0] > 60 for c in slept.call_args_list))  # never slept for hours

    def test_no_credits_fails_at_once_with_a_clear_message(self):
        import io
        from urllib import error, request
        from unittest import mock
        body = io.BytesIO(b'{"error":{"message":"You have no credits remaining. Add credits to continue using the API."}}')
        http = error.HTTPError("u", 429, "Too Many Requests", {}, body)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(request, "urlopen", side_effect=http) as call, \
                mock.patch("time.sleep") as slept:
            m = Model("openai:gpt-5-mini", Path(tmp), key="k")
            with self.assertRaisesRegex(Exception, "no credits or quota left"):
                m.ask("t", "s", "u", {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False})
            self.assertEqual(call.call_count, 1)            # no retries: waiting cannot add credits
            slept.assert_not_called()

