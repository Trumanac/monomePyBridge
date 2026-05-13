"""Direct serial driver for original 40h-protocol monome grids.

Older monome devices (2007-2009 "kit" / "40h" / black-rubber 64) speak a
simple binary protocol over an FTDI USB-serial port. ``serialosc`` 1.4.x
on Windows ships only the ``series`` and ``mext`` protocol drivers — it
does not recognise 40h hardware, so handshakes time out and the device
never appears.

This driver bypasses serialosc entirely and talks the documented 40h wire
protocol directly to the FTDI port. It was originally reverse-engineered
in the MLRVP project against an M64-0858 kit grid; bytes-on-the-wire
behaviour was confirmed empirically (see the comments below).

Wire protocol (host -> device, this firmware revision):

* ``0x20 [(x<<4)|y]``   LED ON
* ``0x21 [(x<<4)|y]``   LED ON (alias)
* ``0x30 [(x<<4)|y]``   LED OFF
* ``0xC0 / 0xC1``       activate ADC port 0 / 1 (single byte)
* ``0xD0 / 0xD1``       deactivate ADC port 0 / 1 (single byte, TX)

Wire protocol (device -> host):

* ``0x00 [(x<<4)|y]``   button release
* ``0x10 [(x<<4)|y]``   button press
* ``0xD0 [val]``        ADC X (after activate)
* ``0xD1 [val]``        ADC Y (after activate)

The 40h protocol has **no LED brightness** — it's binary on/off — so we
threshold incoming 0-15 levels at ``>=1``. Row writes (``0x70|y``) are
documented but silently ignored by this kit firmware revision and are
therefore not used.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from ..base import Device, DeviceInfo, DeviceProtocol

log = logging.getLogger("monomepybridge")


# ── 40h wire-protocol constants ──────────────────────────────────────────
_CMD_BUTTON_UP        = 0x00
_CMD_BUTTON_DOWN      = 0x10
_CMD_LED_ON           = 0x20
_CMD_LED_ON_ALT       = 0x21
_CMD_LED_OFF          = 0x30
_CMD_ACTIVATE_PORT    = 0xC0   # +port (0 or 1)
_CMD_DEACTIVATE_PORT  = 0xD0   # +port (TX); also doubles as RX-data prefix
_CMD_AUX_INPUT_PREFIX = 0xD0   # +port — RX tilt data prefix on this firmware

_BAUD = 9600
_READ_POLL_S = 0.002
_ON_THRESHOLD = 1                # any non-zero level -> LED on
_MAX_CELLS_PER_WRITE = 2         # tiny UART buffer; cap per-packet writes
_TILT_EMA_ALPHA = 0.15           # ~15 Hz cutoff at ~580 Hz sample rate
_TILT_EMIT_HZ = 60.0


def _try_import_serial():
    try:
        import serial  # noqa: F401
        return serial
    except ImportError:
        return None


def probe_40h(com_port: str, timeout: float = 0.6) -> bool:
    """Return True if ``com_port`` can be opened at the 40h baud rate.

    Note: there is no firmware-version query in the 40h protocol, so we
    can only verify that the port opens with DTR/RTS asserted. A real
    handshake test requires lighting an LED and asking the user to
    confirm — out of scope here.
    """
    serial = _try_import_serial()
    if serial is None:
        return False
    try:
        sp = serial.Serial(
            port=com_port, baudrate=_BAUD,
            timeout=timeout, write_timeout=timeout,
            dsrdtr=False, rtscts=False,
        )
        sp.dtr = True
        sp.rts = True
        time.sleep(0.05)
        sp.close()
        return True
    except (serial.SerialException, OSError):
        return False


class Monome40hDevice(Device):
    """Direct-serial driver for original 40h-protocol monome grids."""

    def __init__(self, com_port: str, serial_id: str = "") -> None:
        info = DeviceInfo(
            serial=serial_id or f"40h-{com_port}",
            type_name="monome 40h",
            protocol=DeviceProtocol.PROTO_40H,
            width=8,
            height=8,
            transport=com_port,
            supports_levels=False,
            supports_tilt=True,
            supports_rotation=False,
        )
        super().__init__(info)

        self._com_port = com_port
        self._sp = None
        self._sp_lock = threading.RLock()
        self._serial_mod = _try_import_serial()
        if self._serial_mod is None:
            raise RuntimeError("pyserial not installed — cannot use 40h direct mode")

        # LED state caches: desired vs last-transmitted, plus dirty marks.
        self._led_on = [[False] * self.width for _ in range(self.height)]
        self._led_sent = [[False] * self.width for _ in range(self.height)]
        self._row_dirty = [False] * self.height

        # Threading primitives — created here, started in start().
        self._tx_lock = threading.Lock()
        self._tx_event = threading.Event()
        self._tx_stop = threading.Event()
        self._reader_stop = threading.Event()
        self._writer_thread: Optional[threading.Thread] = None
        self._reader_thread: Optional[threading.Thread] = None

        # Tilt state: EMA-smoothed, rate-limited.
        self._tilt_ema_x: float = 128.0
        self._tilt_ema_y: float = 128.0
        self._tilt_last_emit: float = 0.0
        self._tilt_min_interval: float = 1.0 / _TILT_EMIT_HZ

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        self._open()
        time.sleep(0.050)
        self._init_clear_direct()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            daemon=True,
            name=f"mpb-40h-tx-{self._com_port}",
        )
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name=f"mpb-40h-rx-{self._com_port}",
        )
        self._writer_thread.start()
        self._reader_thread.start()

    def stop(self) -> None:
        log.info("40h stop(): closing %s", self._com_port)
        self._reader_stop.set()
        self._tx_stop.set()
        self._tx_event.set()
        for t in (self._writer_thread, self._reader_thread):
            if t is not None and t.is_alive():
                try:
                    t.join(timeout=0.5)
                except Exception:
                    pass
        if self._sp is not None and self._sp.is_open:
            try:
                self._init_clear_direct()
            except Exception:
                pass
            try:
                self._sp.close()
            except Exception:
                pass
        self._sp = None
        try:
            self._fire_disconnect()
        except Exception:
            log.exception("on_disconnect callback failed")

    # ── transport ────────────────────────────────────────────────────────
    def _open(self) -> None:
        serial = self._serial_mod
        with self._sp_lock:
            self._sp = serial.Serial(
                port=self._com_port,
                baudrate=_BAUD,
                timeout=_READ_POLL_S,
                write_timeout=0.1,
                dsrdtr=False,
                rtscts=False,
            )
            self._sp.dtr = True
            self._sp.rts = True
            try:
                self._sp.reset_input_buffer()
            except Exception:
                pass
        log.info("40h open: %s @ %d 8N1", self._com_port, _BAUD)

    def _init_clear_direct(self) -> None:
        """Send 64x OFF (0x30) per-cell to fully blank the device."""
        try:
            with self._sp_lock:
                if self._sp is None or not self._sp.is_open:
                    return
                for y in range(self.height):
                    for x in range(self.width):
                        self._sp.write(bytes([_CMD_LED_OFF, (x << 4) | (y & 0x0f)]))
                        self._sp.flush()
                        time.sleep(0.010)
            self._led_sent = [[False] * self.width for _ in range(self.height)]
            log.info("40h: cleared all LEDs (64xOFF)")
        except Exception as e:
            log.warning("40h LED clear failed: %s", e)

    # ── LED API (Device interface) ───────────────────────────────────────
    def led_set(self, x: int, y: int, level: int) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        on = level >= _ON_THRESHOLD
        with self._tx_lock:
            self._led_on[y][x] = on
            self._row_dirty[y] = True
        self._tx_event.set()

    def led_all(self, level: int) -> None:
        on = level >= _ON_THRESHOLD
        with self._tx_lock:
            for y in range(self.height):
                for x in range(self.width):
                    self._led_on[y][x] = on
                self._row_dirty[y] = True
        self._tx_event.set()

    def led_row(self, x_offset: int, y: int, levels: list[int]) -> None:
        if not (0 <= y < self.height):
            return
        with self._tx_lock:
            for i, lvl in enumerate(levels[: self.width]):
                x = x_offset + i
                if 0 <= x < self.width:
                    self._led_on[y][x] = lvl >= _ON_THRESHOLD
            self._row_dirty[y] = True
        self._tx_event.set()

    def led_col(self, x: int, y_offset: int, levels: list[int]) -> None:
        if not (0 <= x < self.width):
            return
        with self._tx_lock:
            for i, lvl in enumerate(levels[: self.height]):
                y = y_offset + i
                if 0 <= y < self.height:
                    self._led_on[y][x] = lvl >= _ON_THRESHOLD
                    self._row_dirty[y] = True
        self._tx_event.set()

    # ── tilt ─────────────────────────────────────────────────────────────
    def tilt_set(self, sensor: int, enable: int) -> None:
        """Enable/disable ADC streaming (single-byte 256/m64 commands).

        Both ports always toggled together regardless of ``sensor``.
        """
        try:
            if enable:
                with self._sp_lock:
                    if self._sp is None or not self._sp.is_open:
                        return
                    self._sp.write(bytes([_CMD_ACTIVATE_PORT + 0]))
                    self._sp.flush()
                time.sleep(0.020)
                with self._sp_lock:
                    if self._sp is None or not self._sp.is_open:
                        return
                    self._sp.write(bytes([_CMD_ACTIVATE_PORT + 1]))
                    self._sp.flush()
                log.info("40h tilt: enabled (0xC0, 0xC1)")
            else:
                with self._sp_lock:
                    if self._sp is None or not self._sp.is_open:
                        return
                    self._sp.write(bytes([_CMD_DEACTIVATE_PORT + 0]))
                    self._sp.flush()
                time.sleep(0.020)
                with self._sp_lock:
                    if self._sp is None or not self._sp.is_open:
                        return
                    self._sp.write(bytes([_CMD_DEACTIVATE_PORT + 1]))
                    self._sp.flush()
                log.info("40h tilt: disabled (0xD0, 0xD1)")
        except Exception as e:
            log.warning("40h tilt_set failed: %s", e)

    # ── writer thread ────────────────────────────────────────────────────
    def _writer_loop(self) -> None:
        log.info("40h writer thread started (%s)", self._com_port)
        write_fail_count = 0
        last_fail_log = 0.0
        try:
            while not self._tx_stop.is_set():
                try:
                    with self._tx_lock:
                        has_dirty = any(self._row_dirty)
                    poll_s = 0.003 if has_dirty else 0.016
                    self._tx_event.wait(timeout=poll_s)
                    self._tx_event.clear()

                    pending: list[tuple[int, list[bool]]] = []
                    with self._tx_lock:
                        for y in range(self.height):
                            if self._row_dirty[y]:
                                pending.append((y, list(self._led_on[y])))
                                self._row_dirty[y] = False
                    if not pending:
                        continue

                    all_changes: list[tuple[int, int, bool]] = []
                    for y, row in pending:
                        for x in range(self.width):
                            on = row[x]
                            if self._led_sent[y][x] != on:
                                all_changes.append((y, x, on))

                    changed = all_changes[:_MAX_CELLS_PER_WRITE]
                    overflow = all_changes[_MAX_CELLS_PER_WRITE:]
                    if overflow:
                        retry_rows = {y for y, _, _ in overflow}
                        with self._tx_lock:
                            for ry in retry_rows:
                                self._row_dirty[ry] = True
                    if not changed:
                        continue

                    pkt = bytearray()
                    for y, x, on in changed:
                        pkt.append(_CMD_LED_ON if on else _CMD_LED_OFF)
                        pkt.append((x << 4) | (y & 0x0f))

                    try:
                        with self._sp_lock:
                            sp_out = self._sp
                        if sp_out is None or not sp_out.is_open:
                            raise OSError("serial port not open")
                        sp_out.write(bytes(pkt))
                        sp_out.flush()
                        for y, x, on in changed:
                            self._led_sent[y][x] = on
                        if write_fail_count:
                            log.info("40h write recovered after %d failures",
                                     write_fail_count)
                            write_fail_count = 0
                    except Exception as e:
                        write_fail_count += 1
                        now = time.monotonic()
                        if now - last_fail_log >= 1.0:
                            log.warning("40h write failed (#%d): %s",
                                        write_fail_count, e)
                            last_fail_log = now
                        with self._tx_lock:
                            for y, _ in pending:
                                self._row_dirty[y] = True
                        time.sleep(0.05)
                        if write_fail_count >= 10:
                            self._attempt_port_reopen()
                            write_fail_count = 0
                except Exception as e:
                    log.warning("40h writer iteration error: %s", e, exc_info=True)
                    time.sleep(0.1)
        except BaseException as e:  # noqa: BLE001
            log.error("40h writer thread crashed: %s", e, exc_info=True)
        finally:
            log.info("40h writer thread exiting (%s)", self._com_port)

    def _attempt_port_reopen(self) -> None:
        try:
            if self._sp is not None:
                try:
                    self._sp.close()
                except Exception:
                    pass
            self._sp = None
            time.sleep(0.5)
            self._open()
            log.info("40h: port reopen succeeded")
            self._init_clear_direct()
            with self._tx_lock:
                for y in range(self.height):
                    self._row_dirty[y] = True
        except Exception as e:
            log.warning("40h: port reopen failed: %s", e)
            time.sleep(2.0)

    # ── reader thread ────────────────────────────────────────────────────
    def _reader_loop(self) -> None:
        log.info("40h reader thread started (%s)", self._com_port)
        buf = bytearray()
        try:
            while not self._reader_stop.is_set():
                try:
                    with self._sp_lock:
                        cur = self._sp
                    if cur is None or not cur.is_open:
                        time.sleep(0.05)
                        continue
                    try:
                        data = cur.read(1)
                        if data:
                            avail = cur.in_waiting
                            if avail:
                                data += cur.read(avail)
                    except Exception:
                        time.sleep(0.05)
                        continue
                    if not data:
                        continue
                    buf.extend(data)
                    while len(buf) >= 2:
                        cmd = buf[0]

                        # Button events. 0x10 is reported by this firmware
                        # for press; 0x01 is the libmonome-spec alias.
                        if cmd in (_CMD_BUTTON_UP, _CMD_BUTTON_DOWN, 0x01):
                            pos = buf[1]
                            del buf[:2]
                            state = 0 if cmd == _CMD_BUTTON_UP else 1
                            x = (pos >> 4) & 0x0f
                            y = pos & 0x0f
                            if 0 <= x < self.width and 0 <= y < self.height:
                                try:
                                    self._fire_key(x, y, state)
                                except Exception:
                                    log.exception("40h key callback error")
                            continue

                        # Tilt / ADC data: [0xD0+port, val]. Smooth + emit.
                        if (cmd & 0xF0) == _CMD_AUX_INPUT_PREFIX:
                            val = buf[1]
                            port = cmd & 0x0F
                            del buf[:2]
                            if port == 0:
                                self._tilt_ema_x = (
                                    _TILT_EMA_ALPHA * val
                                    + (1.0 - _TILT_EMA_ALPHA) * self._tilt_ema_x
                                )
                            elif port == 1:
                                self._tilt_ema_y = (
                                    _TILT_EMA_ALPHA * val
                                    + (1.0 - _TILT_EMA_ALPHA) * self._tilt_ema_y
                                )
                            else:
                                continue
                            now = time.monotonic()
                            if now - self._tilt_last_emit >= self._tilt_min_interval:
                                self._tilt_last_emit = now
                                try:
                                    self._fire_tilt(
                                        0,
                                        int(self._tilt_ema_x),
                                        int(self._tilt_ema_y),
                                        128,
                                    )
                                except Exception:
                                    log.exception("40h tilt callback error")
                            continue

                        # Other 2-byte unrecognised opcodes — discard pair.
                        if (0x02 <= cmd <= 0x0f) or (0x11 <= cmd <= 0x1f):
                            del buf[:2]
                            continue

                        # Out of frame — drop one byte and resync.
                        del buf[0]
                except Exception as e:
                    log.warning("40h reader iteration error: %s", e, exc_info=True)
                    time.sleep(0.1)
        except BaseException as e:  # noqa: BLE001
            log.error("40h reader thread crashed: %s", e, exc_info=True)
        finally:
            log.info("40h reader thread exiting (%s)", self._com_port)
