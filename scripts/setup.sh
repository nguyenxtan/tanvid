#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PYTHON=${PYTHON:-python3.12}
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo 'Python 3.12 is required. Set PYTHON to its executable path.' >&2
    exit 1
fi
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"'
if [ ! -d .venv ]; then
    "$PYTHON" -m venv .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 12), "Recreate .venv using Python 3.12"'
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
echo 'Setup complete. Run ./scripts/test.sh or ./scripts/start.sh'
