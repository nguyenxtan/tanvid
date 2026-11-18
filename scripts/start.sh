#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ ! -x .venv/bin/python ]; then
    echo 'Run ./scripts/setup.sh first.' >&2
    exit 1
fi
exec .venv/bin/python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port "${PORT:-8000}"
