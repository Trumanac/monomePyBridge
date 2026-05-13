"""Cross-platform USB / serial device discovery for monome grids.

Uses ``pyserial.tools.list_ports`` so the same code works on Windows,
macOS, and Linux. Devices are matched by USB VID/PID and / or descriptor
strings. Three confidence tiers are reported in the ``DiscoveredPort``:

* ``MATCH_MONOME``  — descriptor contains "monome" (definite hit)
* ``MATCH_FTDI``    — generic FTDI USB-serial chip (likely a 40h kit)
* ``MATCH_UNKNOWN`` — neither, surfaced only on explicit "show all" requests

On the ``DiscoveredPort`` we also record a best-effort guessed protocol
family (``40h`` / ``series`` / ``mext`` / ``unknown``) so the bridge layer
can pick the right driver without re-running heuristics.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Optional

log = logging.getLogger("monomepybridge")


# ── Known monome USB IDs (FTDI chip IDs) ────────────────────────────────
# All monome grids ship with an FTDI chip programmed with custom strings:
#   VID 0x0403  PID 0x6001  (FT232R, used by 40h kit, series, original 64)
#   VID 0x0403  PID 0x6015  (FT231X, used by some newer hardware)
# The descriptor / iManufacturer / iProduct strings vary:
#   "monome", "monome 40h kit", "m64-XXXX", "m128-XXXX", "mk-XXXX", etc.
_FTDI_VID = 0x0403
_FTDI_KNOWN_PIDS = {0x6001, 0x6010, 0x6011, 0x6014, 0x6015}

_MONOME_HINTS = (
    "monome",
    "m40h",
    "m64-",
    "m128-",
    "m256-",
    "mk-",
    "arc",
)


class MatchTier(str, Enum):
    MATCH_MONOME = "monome"
    MATCH_FTDI = "ftdi"
    MATCH_UNKNOWN = "unknown"


class GuessedProtocol(str, Enum):
    PROTO_40H = "40h"
    PROTO_SERIES = "series"
    PROTO_MEXT = "mext"
    PROTO_UNKNOWN = "unknown"


@dataclass(frozen=True)
class DiscoveredPort:
    """Immutable snapshot of a single serial port that may be a monome."""
    device: str                     # e.g. "COM7", "/dev/ttyUSB0"
    description: str = ""
    manufacturer: str = ""
    product: str = ""
    serial_number: str = ""
    vid: Optional[int] = None
    pid: Optional[int] = None
    tier: MatchTier = MatchTier.MATCH_UNKNOWN
    guessed_protocol: GuessedProtocol = GuessedProtocol.PROTO_UNKNOWN

    @property
    def is_monome_hit(self) -> bool:
        return self.tier == MatchTier.MATCH_MONOME

    @property
    def is_likely_monome(self) -> bool:
        return self.tier in (MatchTier.MATCH_MONOME, MatchTier.MATCH_FTDI)

    @property
    def stable_id(self) -> str:
        """Stable identifier across re-enumeration; falls back to device path."""
        if self.serial_number:
            return self.serial_number
        return self.device


def _strings_for(port) -> tuple[str, str, str, str]:
    return (
        getattr(port, "description", "") or "",
        getattr(port, "manufacturer", "") or "",
        getattr(port, "product", "") or "",
        getattr(port, "serial_number", "") or "",
    )


def _classify(port) -> tuple[MatchTier, GuessedProtocol]:
    desc, mfg, prod, ser = _strings_for(port)
    vid = getattr(port, "vid", None)
    pid = getattr(port, "pid", None)
    haystack = " ".join((desc, mfg, prod, ser)).lower()

    is_monome_string = any(h in haystack for h in _MONOME_HINTS)
    is_ftdi = vid == _FTDI_VID and (pid is None or pid in _FTDI_KNOWN_PIDS)

    # Protocol guess: prefer descriptor cues, else default to 40h.
    #
    # Note: serial numbers like "m64-XXXX" are ambiguous — both kit (40h)
    # and pre-mext production grids use that naming. We can't tell the
    # protocol from the descriptor alone; only an active handshake can.
    # We default to 40h here because:
    #   1. serialosc already handles series + mext natively, so users with
    #      those devices typically already have a working stack.
    #   2. The whole point of this app is to fill the 40h gap that
    #      serialosc dropped.
    # Users can override per-device in the GUI.
    if "mext" in haystack:
        proto = GuessedProtocol.PROTO_MEXT
    elif "series" in haystack:
        proto = GuessedProtocol.PROTO_SERIES
    elif is_monome_string or is_ftdi:
        proto = GuessedProtocol.PROTO_40H
    else:
        proto = GuessedProtocol.PROTO_UNKNOWN

    if is_monome_string:
        return MatchTier.MATCH_MONOME, proto
    if is_ftdi:
        return MatchTier.MATCH_FTDI, proto
    return MatchTier.MATCH_UNKNOWN, proto


def _to_discovered(port) -> DiscoveredPort:
    desc, mfg, prod, ser = _strings_for(port)
    tier, proto = _classify(port)
    return DiscoveredPort(
        device=port.device,
        description=desc,
        manufacturer=mfg,
        product=prod,
        serial_number=ser,
        vid=getattr(port, "vid", None),
        pid=getattr(port, "pid", None),
        tier=tier,
        guessed_protocol=proto,
    )


def list_serial_ports(include_unknown: bool = False) -> list[DiscoveredPort]:
    """Enumerate serial ports once and return classified results.

    ``include_unknown=True`` returns every port on the system, useful for
    a "show all" troubleshooting view in the GUI.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        log.warning("pyserial not installed — discovery disabled")
        return []
    out: list[DiscoveredPort] = []
    for p in list_ports.comports():
        dp = _to_discovered(p)
        if include_unknown or dp.is_likely_monome:
            out.append(dp)
    out.sort(key=lambda d: (0 if d.is_monome_hit else 1, d.device))
    return out


# ── Polling scanner ─────────────────────────────────────────────────────
AddedCallback = Callable[[DiscoveredPort], None]
RemovedCallback = Callable[[DiscoveredPort], None]


@dataclass
class _ScannerState:
    known: dict[str, DiscoveredPort] = field(default_factory=dict)


class DeviceScanner:
    """Background poller that emits add / remove events on USB changes.

    Detection is identity-stable on ``serial_number`` when present, falling
    back to the device path. The scanner does NOT open the port itself —
    that's the bridge layer's job.
    """

    def __init__(
        self,
        poll_interval: float = 2.0,
        include_unknown: bool = False,
    ) -> None:
        self._interval = poll_interval
        self._include_unknown = include_unknown
        self._on_added: Optional[AddedCallback] = None
        self._on_removed: Optional[RemovedCallback] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state = _ScannerState()

    def set_callbacks(
        self,
        on_added: Optional[AddedCallback] = None,
        on_removed: Optional[RemovedCallback] = None,
    ) -> None:
        self._on_added = on_added
        self._on_removed = on_removed

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="mpb-discovery",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            try:
                self._thread.join(timeout=self._interval + 0.5)
            except Exception:
                pass

    def scan_once(self) -> list[DiscoveredPort]:
        """Run one pass synchronously, emit any diff events, return current set."""
        ports = list_serial_ports(include_unknown=self._include_unknown)
        self._diff_and_emit(ports)
        return ports

    def known_ports(self) -> list[DiscoveredPort]:
        return list(self._state.known.values())

    # ── internals ────────────────────────────────────────────────────────
    def _loop(self) -> None:
        log.info("device scanner started (poll=%.1fs)", self._interval)
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:
                log.exception("scanner iteration failed")
            self._stop.wait(timeout=self._interval)
        log.info("device scanner stopped")

    def _diff_and_emit(self, ports: Iterable[DiscoveredPort]) -> None:
        seen: dict[str, DiscoveredPort] = {p.stable_id: p for p in ports}
        added = [p for sid, p in seen.items() if sid not in self._state.known]
        removed = [p for sid, p in self._state.known.items() if sid not in seen]
        self._state.known = seen
        for p in added:
            log.info("discovered: %s [%s] %s", p.device, p.tier.value, p.description)
            if self._on_added is not None:
                try:
                    self._on_added(p)
                except Exception:
                    log.exception("on_added callback failed")
        for p in removed:
            log.info("removed: %s", p.device)
            if self._on_removed is not None:
                try:
                    self._on_removed(p)
                except Exception:
                    log.exception("on_removed callback failed")
