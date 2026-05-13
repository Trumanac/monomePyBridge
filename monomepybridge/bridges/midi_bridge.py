"""MIDI bridge for a single grid device.

* Outbound: ``key (x, y, state)`` → Note On / Note Off on a configurable
  channel (1-16). Note number = ``base_note + y * width + x``.
* Inbound:  Note On (vel > 0) → ``led_set(x, y, vel * 15 / 127)``.
            Note Off / Note On vel=0 → ``led_set(x, y, 0)``.
            CC #1..#16 with a "row" convention is intentionally **not**
            implemented to keep the protocol obvious; everything is
            note-based.

On Linux/macOS we open virtual MIDI ports so any DAW sees us instantly.
On Windows ``rtmidi`` does not support virtual ports, so we open the
first available physical port (or none — outbound is still useful via
``loopMIDI``-style loopbacks the user creates).
"""

from __future__ import annotations

import logging
import platform
import threading
from typing import Optional

from ..bridge.base import Device, DeviceCallbacks

log = logging.getLogger("monomepybridge")


def coord_to_note(x: int, y: int, width: int, base_note: int) -> int:
    return int(base_note + y * width + x)


def note_to_coord(note: int, width: int, height: int, base_note: int) -> Optional[tuple[int, int]]:
    rel = int(note) - int(base_note)
    if rel < 0:
        return None
    y, x = divmod(rel, width)
    if 0 <= x < width and 0 <= y < height:
        return x, y
    return None


class MidiBridge:
    """One MIDI in/out pair bound to a single :class:`Device`."""

    def __init__(
        self,
        device: Device,
        channel: int = 1,
        base_note: int = 36,
        port_name: Optional[str] = None,
    ) -> None:
        self.device = device
        self.channel = max(1, min(16, int(channel)))
        self.base_note = int(base_note)
        self.port_name = port_name or f"MonomePyBridge {device.id}"

        self._out = None  # type: ignore[assignment]
        self._in = None   # type: ignore[assignment]
        self._cb: Optional[DeviceCallbacks] = None
        self._lock = threading.Lock()
        self._running = False

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        try:
            import rtmidi
        except Exception as e:
            log.warning("MIDI bridge unavailable (rtmidi import failed): %s", e)
            return
        try:
            self._out = rtmidi.MidiOut()
            self._in = rtmidi.MidiIn()
            opened_out = False
            opened_in = False
            if platform.system() in ("Linux", "Darwin"):
                self._out.open_virtual_port(self.port_name)
                self._in.open_virtual_port(self.port_name)
                opened_out = opened_in = True
            else:
                # Windows: rtmidi has no virtual ports. Try first available.
                out_ports = self._out.get_ports()
                in_ports = self._in.get_ports()
                if out_ports:
                    self._out.open_port(0)
                    opened_out = True
                if in_ports:
                    self._in.open_port(0)
                    opened_in = True
            if not opened_out and not opened_in:
                log.warning(
                    "MIDI bridge: no MIDI ports available on this system. "
                    "Install loopMIDI (Windows) or use IAC Driver (macOS) for loopback."
                )
                self._cleanup()
                return

            self._in.set_callback(self._on_midi_in)
            self._cb = DeviceCallbacks(on_key=self._on_device_key)
            self.device.add_observer(self._cb)
            self._running = True
            log.info(
                "MIDI bridge: %s ch=%d base=%d (out=%s in=%s)",
                self.port_name, self.channel, self.base_note,
                "yes" if opened_out else "no",
                "yes" if opened_in else "no",
            )
        except Exception:
            log.exception("MIDI bridge: failed to start")
            self._cleanup()

    def stop(self) -> None:
        self._running = False
        if self._cb is not None:
            try:
                self.device.remove_observer(self._cb)
            except Exception:
                pass
            self._cb = None
        self._cleanup()
        log.info("MIDI bridge stopped: %s", self.port_name)

    def _cleanup(self) -> None:
        with self._lock:
            for attr in ("_in", "_out"):
                inst = getattr(self, attr, None)
                if inst is None:
                    continue
                try:
                    inst.close_port()
                except Exception:
                    pass
                try:
                    del inst
                except Exception:
                    pass
                setattr(self, attr, None)

    # ── device → MIDI out ────────────────────────────────────────────────
    def _on_device_key(self, x: int, y: int, state: int) -> None:
        if not self._running or self._out is None:
            return
        note = coord_to_note(x, y, self.device.width, self.base_note)
        if not (0 <= note <= 127):
            return
        status = (0x90 if state else 0x80) | (self.channel - 1)
        velocity = 100 if state else 0
        try:
            self._out.send_message([status, note & 0x7F, velocity])
        except Exception:
            log.exception("MIDI send failed")

    # ── MIDI in → device LED ────────────────────────────────────────────
    def _on_midi_in(self, event, _data=None) -> None:
        # event = ([status, data1, data2], timestamp)
        msg, _ts = event
        if len(msg) < 3:
            return
        status = msg[0] & 0xF0
        ch = (msg[0] & 0x0F) + 1
        if ch != self.channel:
            return
        note = msg[1] & 0x7F
        vel = msg[2] & 0x7F
        on = (status == 0x90 and vel > 0)
        off = (status == 0x80) or (status == 0x90 and vel == 0)
        if not (on or off):
            return
        coord = note_to_coord(note, self.device.width, self.device.height, self.base_note)
        if coord is None:
            return
        x, y = coord
        level = int(round(vel * 15.0 / 127.0)) if on else 0
        try:
            self.device.led_set(x, y, level)
        except Exception:
            log.exception("MIDI->LED failed")
