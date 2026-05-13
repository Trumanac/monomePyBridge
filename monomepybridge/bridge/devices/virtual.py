"""In-process virtual grid for development without hardware.

Mirrors :class:`Device` exactly and stores LED state in memory. The GUI
test panel uses this to let users explore the app without owning a
monome, and unit tests use it to drive the OSC layer end-to-end.
"""

from __future__ import annotations

import threading

from ..base import Device, DeviceInfo, DeviceProtocol


class VirtualGridDevice(Device):
    """Non-physical grid — keeps LED state in memory + fires synthetic events."""

    def __init__(
        self,
        serial_id: str = "virt-0001",
        width: int = 8,
        height: int = 8,
    ) -> None:
        if (width, height) == (8, 8):
            type_name = "virtual 8x8"
        elif (width, height) == (16, 8):
            type_name = "virtual 16x8"
        elif (width, height) == (16, 16):
            type_name = "virtual 16x16"
        else:
            type_name = f"virtual {width}x{height}"

        info = DeviceInfo(
            serial=serial_id,
            type_name=type_name,
            protocol=DeviceProtocol.PROTO_VIRTUAL,
            width=width,
            height=height,
            transport="virtual",
            supports_levels=True,
            supports_tilt=False,
            supports_rotation=True,
        )
        super().__init__(info)
        self._lock = threading.Lock()
        self._leds: list[list[int]] = [[0] * width for _ in range(height)]
        self._intensity = 15
        self._running = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
        with self._lock:
            self._leds = [[0] * self.width for _ in range(self.height)]
        self._fire_disconnect()

    # ── LED API ──────────────────────────────────────────────────────────
    def led_set(self, x: int, y: int, level: int) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        with self._lock:
            self._leds[y][x] = max(0, min(15, level))

    def led_all(self, level: int) -> None:
        lvl = max(0, min(15, level))
        with self._lock:
            for y in range(self.height):
                for x in range(self.width):
                    self._leds[y][x] = lvl

    def led_row(self, x_offset: int, y: int, levels: list[int]) -> None:
        if not (0 <= y < self.height):
            return
        with self._lock:
            for i, lvl in enumerate(levels[: self.width]):
                x = x_offset + i
                if 0 <= x < self.width:
                    self._leds[y][x] = max(0, min(15, lvl))

    def led_col(self, x: int, y_offset: int, levels: list[int]) -> None:
        if not (0 <= x < self.width):
            return
        with self._lock:
            for i, lvl in enumerate(levels[: self.height]):
                y = y_offset + i
                if 0 <= y < self.height:
                    self._leds[y][x] = max(0, min(15, lvl))

    def set_intensity(self, level: int) -> None:
        self._intensity = max(0, min(15, level))

    # ── inspection / synthetic input ─────────────────────────────────────
    def get_led(self, x: int, y: int) -> int:
        with self._lock:
            return self._leds[y][x]

    def snapshot(self) -> list[list[int]]:
        with self._lock:
            return [row[:] for row in self._leds]

    def press(self, x: int, y: int) -> None:
        """Synthesize a button press at (x, y) and fire the key callback."""
        self._fire_key(x, y, 1)

    def release(self, x: int, y: int) -> None:
        self._fire_key(x, y, 0)
