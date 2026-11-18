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


if __name__ == "__main__":
    unittest.main()
