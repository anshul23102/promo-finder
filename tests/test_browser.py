"""The in-browser runner's entry point (promo/browser.py): same answer as the command line, safe inputs, clean state.

The Pyodide worker calls exactly these functions, so passing here plus tools/check_browser_parity.mjs (real Pyodide)
covers the browser path.
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from promo.browser import InputError, LIMITS, clean, read_input, run_upload, show_title, write_result

ROOT = Path(__file__).resolve().parent.parent
SHOW = ROOT / "examples" / "the-last-edition"
EPISODE = (SHOW / "episode-001.txt").read_bytes()


def zip_of(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, raw in files.items():
            z.writestr(name, raw)
    return buf.getvalue()


def show_zip() -> bytes:
    return zip_of({p.name: p.read_bytes() for p in sorted(SHOW.glob("*.txt"))})


def comparable(payload: dict) -> dict:
    """Strip what legitimately differs between two runs: the hash of a file that holds the wall-clock time."""
    p = json.loads(json.dumps(payload))
    p.pop("id", None)
    return p


class BrowserRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(clean, self.tmp)

    def test_same_answer_as_the_command_line(self):
        cli_out = self.tmp / "cli"
        subprocess.run([sys.executable, "-m", "promo", str(SHOW), "--model", "rules", "--out", str(cli_out),
                        "--title", "The last edition"], cwd=ROOT, check=True, capture_output=True)
        from promo.payload import build_payload
        from promo.screenplay import load_episodes
        want = build_payload(cli_out, {e.number: e for e in load_episodes(SHOW)})
        got = run_upload("the-last-edition.zip", show_zip(), work=self.tmp / "web")["payload"]
        self.assertEqual(comparable(got), comparable(want))
        self.assertEqual(got["run"]["ai"], False)
        self.assertEqual(len(got["takes"]), 7)

    def test_single_txt_works(self):
        got = run_upload("episode-001.txt", EPISODE, work=self.tmp / "one")["payload"]
        self.assertEqual(got["show"]["episodes"], 1)

    def test_rejects_unusable_input_with_a_plain_message(self):
        for name, data, word in [
            ("show.zip", b"not a zip", "not a readable ZIP"),
            ("show.docx", b"PK", "Choose one .txt"),
            ("show.zip", b"", "empty"),
            ("show.zip", zip_of({"notes.md": b"hi"}), "No .txt"),
        ]:
            with self.subTest(name=name, word=word), self.assertRaises(InputError) as ctx:
                run_upload(name, data, work=self.tmp / "bad")
            self.assertIn(word, str(ctx.exception))
            clean(self.tmp / "bad")

    def test_rejects_bad_scripts(self):
        with self.assertRaises(InputError):
            run_upload("e.txt", b"EPISODE NUMBER: 1\n\n**A:**\nStart: (soon) | End: (00:02.00)\n\"x\"\n", work=self.tmp / "t1")
        with self.assertRaises(InputError):
            run_upload("e.txt", b"EPISODE NUMBER: 1\n\n**A:**\nStart: (00:05.00) | End: (00:02.00)\n\"x\"\n", work=self.tmp / "t3")
        with self.assertRaises(InputError) as ctx:
            run_upload("s.zip", zip_of({"a/episode-001.txt": EPISODE, "b/ep_1.txt": EPISODE}), work=self.tmp / "t2")
        self.assertIn("Duplicate episode number", str(ctx.exception))

    def test_decompressed_bounds_hold_even_if_the_header_lies(self):
        big = b"EPISODE NUMBER: 1\n" + b"x" * 3000
        with self.assertRaises(InputError):
            read_input("s.zip", zip_of({"a.txt": big, "b.txt": big}), {"total_bytes": 4000})
        with self.assertRaises(InputError):
            read_input("s.zip", zip_of({"a.txt": big}), {"file_bytes": 1000})
        with self.assertRaises(InputError):
            read_input("s.zip", zip_of({f"{i}.txt": b"x" for i in range(5)}), {"files": 3})
        with self.assertRaises(InputError):
            read_input("s.zip", b"x" * 100, {"input_bytes": 50})
        # a forged central-directory size must not let a large entry through
        data = bytearray(zip_of({"a.txt": b"y" * 5000}))
        sizes = [i for i in range(len(data) - 4) if data[i:i + 4] == (5000).to_bytes(4, "little")]
        for i in sizes:
            data[i:i + 4] = (10).to_bytes(4, "little")
        try:
            read_input("s.zip", bytes(data), {"file_bytes": 1000})
        except InputError:
            pass
        else:
            self.fail("a forged size slipped through")

    def test_unsafe_paths_and_system_files(self):
        got = read_input("s.zip", zip_of({"__MACOSX/._a.txt": b"x", ".hidden.txt": b"x", "ok/episode-002.txt": EPISODE}))
        self.assertEqual(list(got), ["ok/episode-002.txt"])
        with self.assertRaises(InputError):
            read_input("s.zip", zip_of({"../evil.txt": b"x"}))

    def test_valid_zero_result_and_two_successive_shows(self):
        tiny = b"EPISODE NUMBER: 1\n\n**A (calm):**\nStart: (00:00.00) | End: (00:02.00)\n\"Hello.\"\n"
        zero = run_upload("tiny.txt", tiny, work=self.tmp / "z")["payload"]
        self.assertEqual(zero["takes"], [])
        first = run_upload("one.zip", show_zip(), work=self.tmp / "r1")["payload"]
        clean(self.tmp / "r1")
        second = run_upload("two.txt", EPISODE, work=self.tmp / "r2")["payload"]
        self.assertEqual(first["show"]["episodes"], 7)
        self.assertEqual(second["show"]["episodes"], 1)      # nothing carried over from the first show
        self.assertFalse((self.tmp / "r1").exists())

    def test_result_files_and_title(self):
        work = self.tmp / "f"
        result = run_upload("My_show-v2.zip", show_zip(), work=work)
        write_result(result, work)
        names = zipfile.ZipFile(work / "run.zip").namelist()
        for expected in ("promos.csv", "promos.json", "cutlist.edl", "posting_plan.md"):
            self.assertIn(expected, names)
        self.assertEqual(show_title("My_show-v2.zip"), "My show v2")
        self.assertEqual(show_title(".zip"), "Your show")
        self.assertTrue(LIMITS["input_bytes"] > 0)


if __name__ == "__main__":
    unittest.main()
