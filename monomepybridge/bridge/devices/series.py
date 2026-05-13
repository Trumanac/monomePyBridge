"""Stub for ``series`` protocol grids (64 / 128 / 256, pre-mext production).

These grids speak the older ``series`` binary protocol over USB-serial
(typically through an FTDI chip). They support full 0-15 LED brightness
levels but use a different framing than 40h.

Implementation deferred — the 40h driver gets us the hardware MLRVP
targeted; series support will land once the project has hardware to
test against.
"""

from __future__ import annotations

from ..base import Device, DeviceInfo, DeviceProtocol


class MonomeSeriesDevice(Device):
    """Placeholder — raises on instantiation until implemented."""

    def __init__(self, com_port: str, type_name: str, serial_id: str = "") -> None:
        raise NotImplementedError(
            "series protocol driver not yet implemented "
            "(target: 64 / 128 / 256 pre-mext production grids)"
        )

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def led_set(self, x: int, y: int, level: int) -> None: ...
    def led_all(self, level: int) -> None: ...
    def led_row(self, x_offset: int, y: int, levels: list[int]) -> None: ...
    def led_col(self, x: int, y_offset: int, levels: list[int]) -> None: ...
