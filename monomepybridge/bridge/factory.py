"""Driver factory: pick the right :class:`Device` for a discovered port.

Keeps the discovery layer ignorant of concrete driver classes and lets the
GUI / app code call :func:`build_device` without a long if/elif ladder.
"""

from __future__ import annotations

from typing import Optional

from ..discovery.scanner import DiscoveredPort, GuessedProtocol
from .base import Device
from .devices.monome40h import Monome40hDevice


def build_device(port: DiscoveredPort) -> Optional[Device]:
    """Construct (but do not start) the appropriate driver for ``port``.

    Returns ``None`` if no driver is available for the guessed protocol.
    Caller is responsible for calling :meth:`Device.start` and wiring
    callbacks before use.
    """
    proto = port.guessed_protocol
    serial_id = port.serial_number or ""

    if proto == GuessedProtocol.PROTO_40H:
        return Monome40hDevice(port.device, serial_id=serial_id)

    if proto == GuessedProtocol.PROTO_SERIES:
        # Deferred — see devices/series.py.
        return None

    if proto == GuessedProtocol.PROTO_MEXT:
        # Deferred — see devices/mext.py.
        return None

    return None
