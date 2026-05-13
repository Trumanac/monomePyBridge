#!/usr/bin/env bash
# MonomePyBridge launcher (macOS/Linux, dev mode using local .venv)
set -euo pipefail
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
    exec ".venv/bin/python" -m monomepybridge "$@"
else
    echo ".venv not found. Run setup first:"
    echo "    python3.11 -m venv .venv"
    echo "    source .venv/bin/activate"
    echo "    pip install -e .[dev]"
    exit 1
fi
