#!/usr/bin/env bash
# One command that must pass before a release: tests, the model-swap smoke test, a fresh build of the demo AND the
# in-browser runner, and byte-level parity between real Pyodide and native Python on bundled and generated inputs.
#
#   tools/release_check.sh            # uses npm to fetch the pinned pyodide package (hash-checked against ui-claude/runtime.lock.json)
#   PYODIDE_PKG=/path/to/package tools/release_check.sh
#
# Run from the repo root. Writes only to a temporary folder (printed at the end). Needs python3, node and npm.
set -euo pipefail
cd "$(dirname "$0")/.."
WORK="$(mktemp -d)"
VERSION="$(python3 -c "import json;print(json.load(open('ui-claude/runtime.lock.json'))['pyodide'])")"
RELEASE="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"

echo "== 1. Python tests"
python3 -m unittest discover -s tests

echo "== 2. Model-swap smoke test (local stand-in endpoint)"
python3 tools/swap_smoke_test.py

echo "== 3. Pinned Pyodide $VERSION"
if [ -z "${PYODIDE_PKG:-}" ]; then
  (cd "$WORK" && npm pack "pyodide@$VERSION" --silent >/dev/null && tar xzf "pyodide-$VERSION.tgz")
  PYODIDE_PKG="$WORK/package"
  EXPECT="$(python3 -c "import json;print(json.load(open('ui-claude/runtime.lock.json'))['npm_tarball_sha256'])")"
  GOT="$(shasum -a 256 "$WORK/pyodide-$VERSION.tgz" | cut -d' ' -f1)"
  [ "$EXPECT" = "$GOT" ] || { echo "npm tarball hash differs from the pinned one"; exit 1; }
fi

echo "== 4. Build the demo site and the runner"
python3 -m promo examples/the-last-edition --model rules --out "$WORK/run" >/dev/null
python3 ui-claude/build_data.py --run "$WORK/run" --pack examples/the-last-edition --out "$WORK/site" --demo
python3 ui-claude/build_runner.py --site "$WORK/site" --runtime "$PYODIDE_PKG" --release "$RELEASE"

echo "== 5. Pyodide vs native Python (same inputs, every output file)"
python3 tools/make_load_fixture.py "$WORK/load50.zip" >/dev/null
printf 'not a zip' > "$WORK/broken.zip"
printf 'EPISODE NUMBER: 1\n\n**A:**\nStart: (soon) | End: (00:02.00)\n"x"\n' > "$WORK/malformed.txt"
node tools/check_browser_parity.mjs --site "$WORK/site" \
  examples/the-last-edition/episode-001.txt "$WORK/site/run/examples/the-last-edition.zip" "$WORK/site/run/examples/last-edition.zip" \
  "$WORK/load50.zip" "$WORK/broken.zip" "$WORK/malformed.txt"

echo
echo "Release gate passed. Scratch build: $WORK/site (serve it with: python3 -m http.server 8766 --bind 127.0.0.1 --directory $WORK/site)"
