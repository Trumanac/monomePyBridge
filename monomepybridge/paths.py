"""Cross-platform paths for config, logs, and cache.

Uses :mod:`platformdirs` so we land in:

* Windows  — ``%APPDATA%\\MonomePyBridge``
* macOS    — ``~/Library/Application Support/MonomePyBridge``
* Linux    — ``~/.config/MonomePyBridge``
"""

from __future__ import annotations

import sys
from pathlib import Path

from platformdirs import PlatformDirs

_APP_NAME = "MonomePyBridge"
_APP_AUTHOR = "Trumanac"

_dirs = PlatformDirs(_APP_NAME, _APP_AUTHOR, roaming=True)


def config_dir() -> Path:
    """Return (and create) the user config directory."""
    p = Path(_dirs.user_config_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_dir() -> Path:
    """Return (and create) the user log directory."""
    p = Path(_dirs.user_log_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    """Return (and create) the user cache directory."""
    p = Path(_dirs.user_cache_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_file() -> Path:
    """Path to the main JSON config file."""
    return config_dir() / "config.json"


def devices_file() -> Path:
    """Path to the per-device profile store."""
    return config_dir() / "devices.json"


def ws_demo_file() -> Path | None:
    """Return the best available ws_demo.html path for dev and bundled runs."""
    here = Path(__file__).resolve()
    candidates = [
        # Source checkout.
        here.parents[1] / "tests" / "ws_demo.html",
        # Editable install / packaged resource within the module tree.
        here.parent / "resources" / "ws_demo.html",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        # PyInstaller extraction root.
        candidates.append(Path(meipass) / "monomepybridge" / "resources" / "ws_demo.html")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
