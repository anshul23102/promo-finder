"""Write a 50-episode synthetic ZIP for load and parity tests (made up; repeats the seven example episodes under new numbers).

    python3 tools/make_load_fixture.py OUT.zip [--episodes 50]
"""
import argparse
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--episodes", type=int, default=50)
    args = ap.parse_args()
    sources = [p.read_text(encoding="utf-8") for p in sorted((ROOT / "examples" / "the-last-edition").glob("*.txt"))]
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in range(1, args.episodes + 1):
            text = sources[(n - 1) % len(sources)]
            text = re.sub(r"EPISODE NUMBER:\s*Episode \d+", f"EPISODE NUMBER: Episode {n}", text, count=1)
            info = zipfile.ZipInfo(f"episode-{n:03d}.txt", (1980, 1, 1, 0, 0, 0))
            z.writestr(info, text)
    print(f"wrote {args.out} ({args.episodes} episodes)")


if __name__ == "__main__":
    main()
