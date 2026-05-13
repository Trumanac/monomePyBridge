"""Abstract device interface — shared API across all monome grid protocols.

All concrete drivers (40h, series, mext, virtual) implement :class:`Device`
and emit events via the callback hooks. The :class:`DeviceInfo` dataclass
carries identifying metadata used by the discovery layer and by the OSC
``/sys/info`` reply.

LED brightness is normalised to 0-15 across the entire app. Drivers that
support only binary on/off (e.g. 40h) threshold internally.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class DeviceProtocol(str, Enum):
    """Wire protocol family used by the device."""
    PROTO_40H = "40h"
    PROTO_SERIES = "series"
    PROTO_MEXT = "mext"
    PROTO_VIRTUAL = "virtual"


# ── Standard device-type lookup ─────────────────────────────────────────
# Maps a short type name (as it appears in serialosc /sys/info replies and
# in monome serial-number prefixes) to (width, height) and protocol family.
_KNOWN_TYPES: dict[str, tuple[int, int, DeviceProtocol]] = {
    "monome 40h":     (8, 8,   DeviceProtocol.PROTO_40H),
    "monome 64":      (8, 8,   DeviceProtocol.PROTO_SERIES),
    "monome 128":     (16, 8,  DeviceProtocol.PROTO_SERIES),
    "monome 256":     (16, 16, DeviceProtocol.PROTO_SERIES),
    "monome 64 mext": (8, 8,   DeviceProtocol.PROTO_MEXT),
    "monome 128 mext":(16, 8,  DeviceProtocol.PROTO_MEXT),
    "monome 256 mext":(16, 16, DeviceProtocol.PROTO_MEXT),
    "virtual 8x8":    (8, 8,   DeviceProtocol.PROTO_VIRTUAL),
    "virtual 16x8":   (16, 8,  DeviceProtocol.PROTO_VIRTUAL),
    "virtual 16x16":  (16, 16, DeviceProtocol.PROTO_VIRTUAL),
}


def lookup_dimensions(type_name: str) -> tuple[int, int]:
    """Best-effort dimension lookup by friendly type name."""
    return _KNOWN_TYPES.get(type_name.lower(), (8, 8))[:2]


@dataclass
class DeviceInfo:
    """Identity + capability snapshot for a single physical device."""
    serial: str                        # e.g. "m64-0858"
    type_name: str                     # e.g. "monome 40h"
    protocol: DeviceProtocol
    width: int
    height: int
    transport: str = ""                # e.g. "COM7", "/dev/ttyUSB0"
    firmware_version: str = ""
    supports_levels: bool = False      # True for 64/128/256 mext, False for 40h
    supports_tilt: bool = False
    supports_rotation: bool = False    # only mext + series support setting it on-device
    rotation: int = 0                  # current rotation in degrees (0/90/180/270)

    @property
    def cells(self) -> int:
        return self.width * self.height


# Callback signatures — kept simple so concrete drivers remain easy to wire up.
KeyCallback = Callable[[int, int, int], None]              # (x, y, state 0|1)
TiltCallback = Callable[[int, int, int, int], None]        # (n, x, y, z) raw 0-255
DisconnectCallback = Callable[[], None]


@dataclass
class DeviceCallbacks:
    on_key: Optional[KeyCallback] = None
    on_tilt: Optional[TiltCallback] = None
    on_disconnect: Optional[DisconnectCallback] = None


class Device(ABC):
    """Common interface for every grid driver.

    Drivers are responsible for thread safety of their own internal state.
    Public methods on this interface are safe to call from any thread once
    :meth:`start` has returned.
    """

    def __init__(self, info: DeviceInfo) -> None:
        self.info = info
        self._cb = DeviceCallbacks()
        self._observers: list[DeviceCallbacks] = []

    # ── identity passthroughs ────────────────────────────────────────────
    @property
    def id(self) -> str:
        return self.info.serial

    @property
    def width(self) -> int:
        return self.info.width

    @property
    def height(self) -> int:
        return self.info.height

    @property
    def rotation(self) -> int:
        return self.info.rotation

    # ── lifecycle ────────────────────────────────────────────────────────
    @abstractmethod
    def start(self) -> None:
        """Open the underlying transport and start I/O threads."""

    @abstractmethod
    def stop(self) -> None:
        """Cleanly shut down threads, blank LEDs, close transport."""

    # ── LED API (brightness 0-15) ────────────────────────────────────────
    @abstractmethod
    def led_set(self, x: int, y: int, level: int) -> None: ...

    @abstractmethod
    def led_all(self, level: int) -> None: ...

    @abstractmethod
    def led_row(self, x_offset: int, y: int, levels: list[int]) -> None: ...

    @abstractmethod
    def led_col(self, x: int, y_offset: int, levels: list[int]) -> None: ...

    def led_map(self, x_offset: int, y_offset: int, levels: list[list[int]]) -> None:
        """Write an 8x8 quadrant. Default impl falls back to per-row writes.

        ``levels`` must be 8 rows of 8 brightness values (0-15).
        """
        for row_idx, row in enumerate(levels[:8]):
            self.led_row(x_offset, y_offset + row_idx, list(row[:8]))

    # ── device options ───────────────────────────────────────────────────
    def set_intensity(self, level: int) -> None:
        """Set global LED intensity (0-15). Default: no-op."""
        return

    def set_rotation(self, degrees: int) -> None:
        """Set device rotation (0/90/180/270). Default: just record locally."""
        self.info.rotation = int(degrees) % 360

    def tilt_set(self, sensor: int, enable: int) -> None:
        """Enable/disable tilt sensor streaming. Default: no-op."""
        return

    # ── callbacks ────────────────────────────────────────────────────────
    def set_callbacks(self, callbacks: DeviceCallbacks) -> None:
        self._cb = callbacks

    def add_observer(self, callbacks: DeviceCallbacks) -> None:
        """Add an extra :class:`DeviceCallbacks` fan-out (e.g. the GUI)."""
        self._observers.append(callbacks)

    def remove_observer(self, callbacks: DeviceCallbacks) -> None:
        try:
            self._observers.remove(callbacks)
        except ValueError:
            pass

    # Internal helpers for drivers to fire events safely.
    def _fire_key(self, x: int, y: int, state: int) -> None:
        cb = self._cb.on_key
        if cb is not None:
            cb(x, y, state)
        for obs in list(self._observers):
            if obs.on_key is not None:
                try:
                    obs.on_key(x, y, state)
                except Exception:
                    pass

    def _fire_tilt(self, n: int, x: int, y: int, z: int) -> None:
        cb = self._cb.on_tilt
        if cb is not None:
            cb(n, x, y, z)
        for obs in list(self._observers):
            if obs.on_tilt is not None:
                try:
                    obs.on_tilt(n, x, y, z)
                except Exception:
                    pass

    def _fire_disconnect(self) -> None:
        cb = self._cb.on_disconnect
        if cb is not None:
            cb()
        for obs in list(self._observers):
            if obs.on_disconnect is not None:
                try:
                    obs.on_disconnect()
                except Exception:
                    pass
