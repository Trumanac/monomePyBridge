"""Stub for ``mext`` protocol grids (current production hardware).

Modern monome devices (current grid, arc, etc.) speak ``mext`` — a
length-prefixed binary protocol over USB-serial. Full brightness, tilt,
and on-device rotation are supported.

Implementation deferred — see ``series.py`` rationale.
"""

from __future__ import annotations

from ..base import Device


class MonomeMextDevice(Device):
    """Placeholder — raises on instantiation until implemented."""

    def __init__(self, com_port: str, type_name: str, serial_id: str = "") -> None:
        raise NotImplementedError(
            "mext protocol driver not yet implemented "
            "(target: current production grid + arc hardware)"
        )

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def led_set(self, x: int, y: int, level: int) -> None: ...
    def led_all(self, level: int) -> None: ...
    def led_row(self, x_offset: int, y: int, levels: list[int]) -> None: ...
    def led_col(self, x: int, y_offset: int, levels: list[int]) -> None: ...
