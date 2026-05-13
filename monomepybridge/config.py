"""Persistent app + per-device configuration.

Two JSON files live under :func:`paths.config_dir`:

* ``config.json``  — global app settings (OSC defaults, GUI prefs, etc.)
* ``devices.json`` — per-device profiles keyed by serial number.

Both are loaded lazily and saved atomically.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .paths import config_file, devices_file


# ── Atomic JSON helpers ─────────────────────────────────────────────────

def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── App-wide settings ───────────────────────────────────────────────────

@dataclass
class AppConfig:
    osc_default_host: str = "127.0.0.1"
    osc_serialoscd_port: int = 12002
    osc_device_base_port: int = 13000  # auto-allocated upward per device
    legacy_mode_enabled: bool = False  # extra fixed-prefix monomeserial-style server
    legacy_listen_port: int = 8080
    legacy_send_port: int = 8000
    minimize_to_tray: bool = True
    start_minimized: bool = False
    log_level: str = "INFO"

    @classmethod
    def load(cls) -> AppConfig:
        data = _read_json(config_file())
        defaults = cls()
        merged = {**asdict(defaults), **data}
        # Drop unknown keys so we never crash on schema drift.
        return cls(**{k: merged[k] for k in asdict(defaults)})

    def save(self) -> None:
        _write_json(config_file(), asdict(self))


# ── Per-device profiles ─────────────────────────────────────────────────

@dataclass
class DeviceProfile:
    serial: str
    prefix: str = "/monome"
    rotation: int = 0
    intensity: int = 15
    osc_host: str = "127.0.0.1"
    osc_app_port: int = 8000   # where we send key/tilt events to the user's app
    osc_listen_port: int = 0   # where we receive LED commands; 0 = auto
    tilt_enabled: bool = False
    midi_enabled: bool = False
    websocket_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceProfile:
        defaults = cls(serial=data.get("serial", ""))
        merged = {**asdict(defaults), **data}
        return cls(**{k: merged[k] for k in asdict(defaults)})


@dataclass
class DeviceProfileStore:
    profiles: dict[str, DeviceProfile] = field(default_factory=dict)

    @classmethod
    def load(cls) -> DeviceProfileStore:
        raw = _read_json(devices_file())
        profiles = {
            serial: DeviceProfile.from_dict({"serial": serial, **(d or {})})
            for serial, d in raw.items()
            if isinstance(d, dict)
        }
        return cls(profiles=profiles)

    def save(self) -> None:
        data = {serial: p.to_dict() for serial, p in self.profiles.items()}
        _write_json(devices_file(), data)

    def get_or_create(self, serial: str) -> DeviceProfile:
        if serial not in self.profiles:
            self.profiles[serial] = DeviceProfile(serial=serial)
        return self.profiles[serial]

    def remove(self, serial: str) -> bool:
        """Forget the saved profile for ``serial``. Returns True if it existed."""
        if serial in self.profiles:
            del self.profiles[serial]
            return True
        return False
