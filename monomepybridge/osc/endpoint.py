"""Low-level OSC socket server + sender used by the bridge.

We deliberately avoid ``pythonosc.dispatcher.Dispatcher`` and the
threading server bundled with python-osc so we can:

* Bind one UDP socket per logical OSC endpoint (per-device server,
  serialoscd discovery, etc.) and use the *same socket* for both RX and
  arbitrary-target TX. This is the same socket model used by libmonome /
  serialosc and lets clients reply-route via the source port if they
  ever need to.
* Allocate ports by passing ``port=0`` and reading back the assigned
  port — needed for serialoscd-style auto-allocation.
* Route by full OSC address with first-match-wins prefix dispatch.

The wire format itself (parsing / building) we leave to ``python-osc``.
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Callable, Optional

from pythonosc import osc_message_builder
from pythonosc.osc_packet import OscPacket
from pythonosc.parsing.osc_types import BuildError

log = logging.getLogger("monomepybridge")


# Handler signature: (address, args, source_addr) -> None
OscHandler = Callable[[str, list, tuple[str, int]], None]


def build_osc_message(address: str, args: list) -> bytes:
    """Encode an OSC message; raises ``BuildError`` on bad args."""
    b = osc_message_builder.OscMessageBuilder(address=address)
    for a in args:
        b.add_arg(a)
    return b.build().dgram


class OscEndpoint:
    """A single UDP socket carrying both inbound dispatch and outbound sends.

    Handlers are matched by exact address first, then by registered
    prefix (longest-prefix wins). A wildcard handler registered with
    ``register_default()`` catches everything else.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 0) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.settimeout(0.25)
        self._bound_host, self._bound_port = self._sock.getsockname()

        self._exact: dict[str, OscHandler] = {}
        self._prefix: list[tuple[str, OscHandler]] = []  # sorted longest-first
        self._default: Optional[OscHandler] = None

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── lifecycle ────────────────────────────────────────────────────────
    @property
    def port(self) -> int:
        return self._bound_port

    @property
    def host(self) -> str:
        return self._bound_host

    def start(self, name: str = "mpb-osc") -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=name)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            try:
                self._thread.join(timeout=0.5)
            except Exception:
                pass
        try:
            self._sock.close()
        except Exception:
            pass

    # ── handler registration ─────────────────────────────────────────────
    def register(self, address: str, handler: OscHandler) -> None:
        self._exact[address] = handler

    def unregister(self, address: str) -> None:
        self._exact.pop(address, None)

    def register_prefix(self, prefix: str, handler: OscHandler) -> None:
        # Maintain longest-first so nested prefixes resolve correctly.
        self._prefix = [(p, h) for p, h in self._prefix if p != prefix]
        self._prefix.append((prefix, handler))
        self._prefix.sort(key=lambda x: -len(x[0]))

    def unregister_prefix(self, prefix: str) -> None:
        self._prefix = [(p, h) for p, h in self._prefix if p != prefix]

    def register_default(self, handler: OscHandler) -> None:
        self._default = handler

    # ── send ─────────────────────────────────────────────────────────────
    def send(self, host: str, port: int, address: str, *args) -> None:
        try:
            dgram = build_osc_message(address, list(args))
        except BuildError as e:
            log.warning("osc build failed for %s: %s", address, e)
            return
        try:
            self._sock.sendto(dgram, (host, int(port)))
        except OSError as e:
            log.debug("osc send to %s:%d failed: %s", host, port, e)

    # ── recv loop ────────────────────────────────────────────────────────
    def _loop(self) -> None:
        log.debug("osc endpoint listening on %s:%d", self._bound_host, self._bound_port)
        while not self._stop.is_set():
            try:
                data, src = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                packet = OscPacket(data)
            except Exception as e:
                log.debug("osc parse failed from %s: %s", src, e)
                continue
            for tm in packet.messages:
                msg = tm.message
                addr = msg.address
                args = list(msg.params)
                handler = self._exact.get(addr)
                if handler is None:
                    for pfx, h in self._prefix:
                        if addr == pfx or addr.startswith(pfx + "/"):
                            handler = h
                            break
                if handler is None:
                    handler = self._default
                if handler is None:
                    log.debug("osc: no handler for %s from %s", addr, src)
                    continue
                try:
                    handler(addr, args, src)
                except Exception:
                    log.exception("osc handler raised for %s", addr)
        log.debug("osc endpoint closed (%s:%d)", self._bound_host, self._bound_port)
