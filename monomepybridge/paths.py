"""Cross-platform paths for config, logs, and cache.

Uses :mod:`platformdirs` so we land in:

* Windows  — ``%APPDATA%\\MonomePyBridge``
* macOS    — ``~/Library/Application Support/MonomePyBridge``
* Linux    — ``~/.config/MonomePyBridge``
"""

from __future__ import annotations

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
