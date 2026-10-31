#!/usr/bin/env bash
# Run the Python tests the fast way; arguments go to pytest (default: tests, in parallel).
#
#   scripts/test.sh                                   the whole suite
#   scripts/test.sh tests/seam2/test_deals_api.py     one file, also in parallel
#
# Keeps Python, the venv and the tests' temporary files on local disk ($FS_TEST_DIR): imports are
# slow on a network filesystem such as /scratch. The first run builds the venv, later ones reuse it.
# Settings: FS_TEST_DIR (default /tmp/$USER-flight-scanner-test), FS_TEST_WORKERS (default 8).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# On roihu uv, initdb and pg_ctl come from the conda env next to the checkout.
CONDA_BIN="$ROOT/../miniconda3/envs/flight-scanner/bin"
if ! command -v initdb >/dev/null 2>&1 && [ -d "$CONDA_BIN" ]; then
  PATH="$PATH:$(cd "$CONDA_BIN" && pwd)"
fi
for tool in uv initdb pg_ctl; do
  command -v "$tool" >/dev/null 2>&1 || { echo "test.sh: $tool not found on PATH" >&2; exit 1; }
done

DIR="${FS_TEST_DIR:-/tmp/${USER:-$(id -un)}-flight-scanner-test}"
mkdir -p "$DIR/tmp"
export UV_PYTHON_INSTALL_DIR="$DIR/python" UV_CACHE_DIR="$DIR/uv-cache"
export UV_PROJECT_ENVIRONMENT="$DIR/venv" UV_PYTHON_PREFERENCE=only-managed
export TMPDIR="$DIR/tmp" FS_PG_TMP="$DIR/tmp"
uv sync --frozen --quiet --python 3.12

WORKERS="${FS_TEST_WORKERS:-8}"
exec "$DIR/venv/bin/python" -m pytest -n "$WORKERS" --dist worksteal "${@:-tests}"
