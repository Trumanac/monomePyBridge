#!/usr/bin/env bash
# MonomePyBridge launcher (macOS/Linux, dev mode using local .venv)
set -euo pipefail
cd "$(dirname "$0")"

supports_project_python() {
    local pybin="$1"
    "$pybin" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)'
}

if [ -x ".venv/bin/python" ]; then
    if ! supports_project_python ".venv/bin/python"; then
        echo "Existing .venv uses an unsupported Python version."
        echo "MonomePyBridge requires Python >=3.11,<3.13."
        echo ""
        echo "Recreate the venv with Python 3.11 or 3.12:"
        echo "    rm -rf .venv"
        echo "    python3.12 -m venv .venv   # or python3.11"
        echo "    source .venv/bin/activate"
        echo "    pip install -e .[dev]"
        exit 1
    fi
    exec ".venv/bin/python" -m monomepybridge "$@"
else
    echo ".venv not found. Run setup first:"
    echo "    python3.12 -m venv .venv   # or python3.11"
    echo "    source .venv/bin/activate"
    echo "    pip install -e .[dev]"
    echo ""
    echo "If macOS says python3 is too old, install a supported version:"
    echo "    brew install python@3.12"
    echo "    /opt/homebrew/bin/python3.12 -m venv .venv"
    exit 1
fi
