"""serialosc-compatible discovery server (UDP 12002 by default).

Implements just enough of the serialosc daemon's discovery protocol that
existing clients (Max patches via ``serialosc.maxpat``, libmonome /
pymonome apps, browser bridges, etc.) detect MonomePyBridge as if it
were the real serialosc daemon:

Inbound from clients:

* ``/serialosc/list <host:str> <port:int>`` — for each connected device,
  reply to ``host:port`` with ``/serialosc/device <id> <type> <port>``.
* ``/serialosc/notify <host:str> <port:int>`` — register a one-shot
  subscription. On the *next* device add or remove, send ONE message to
  ``host:port``: ``/serialosc/add <id>`` or ``/serialosc/remove <id>``,
  then drop the subscription. (This matches the real serialosc behaviour
  — clients re-subscribe after each notification.)

The :class:`DiscoveryServer` itself is transport-agnostic: device
listings come from a callable supplied at construction time, and add /
remove notifications are pushed in via :meth:`broadcast_add` /
:meth:`broadcast_remove`. The :class:`BridgeManager` owns the wiring.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Iterable

from ..osc import protocol as P
from ..osc.endpoint import OscEndpoint

log = logging.getLogger("monomepybridge")


@dataclass(frozen=True)
class AdvertisedDevice:
    """What we advertise about an active device on /serialosc/list."""
    id: str
    type_name: str
    port: int


# Snapshot provider: returns the current list of advertised devices.
DeviceListProvider = Callable[[], Iterable[AdvertisedDevice]]


class DiscoveryServer:
    """serialosc /serialosc/* discovery daemon."""

    def __init__(
        self,
        device_provider: DeviceListProvider,
        host: str = "0.0.0.0",
        port: int = P.DEFAULT_SERIALOSC_PORT,
    ) -> None:
        self._provider = device_provider
        self._endpoint = OscEndpoint(host=host, port=port)
        self._notify_lock = threading.Lock()
        self._notify_subscribers: list[tuple[str, int]] = []
        self._endpoint.register(P.SERIALOSC_LIST, self._h_list)
        self._endpoint.register(P.SERIALOSC_NOTIFY, self._h_notify)

    @property
    def port(self) -> int:
        return self._endpoint.port

    @property
    def host(self) -> str:
        return self._endpoint.host

    def start(self) -> None:
        self._endpoint.start(name="mpb-serialoscd")
        log.info("serialoscd listening on %s:%d", self.host, self.port)

    def stop(self) -> None:
        self._endpoint.stop()

    # ── inbound handlers ─────────────────────────────────────────────────
    def _h_list(self, addr: str, args: list, src: tuple[str, int]) -> None:
        if len(args) < 2 or not isinstance(args[0], str) or not isinstance(args[1], int):
            log.debug("/serialosc/list: bad args from %s: %r", src, args)
            return
        target = (args[0], int(args[1]))
        for d in self._provider():
            self._endpoint.send(target[0], target[1],
                                P.SERIALOSC_DEVICE, d.id, d.type_name, d.port)
        log.debug("/serialosc/list -> %s:%d (%d devices)",
                  target[0], target[1], len(list(self._provider())))

    def _h_notify(self, addr: str, args: list, src: tuple[str, int]) -> None:
        if len(args) < 2 or not isinstance(args[0], str) or not isinstance(args[1], int):
            log.debug("/serialosc/notify: bad args from %s: %r", src, args)
            return
        target = (args[0], int(args[1]))
        with self._notify_lock:
            self._notify_subscribers.append(target)
        log.debug("/serialosc/notify -> %s:%d (subscribed)", target[0], target[1])

    # ── outbound: fired by BridgeManager on device add / remove ──────────
    def broadcast_add(self, device_id: str) -> None:
        self._drain_notify(P.SERIALOSC_ADD, device_id)

    def broadcast_remove(self, device_id: str) -> None:
        self._drain_notify(P.SERIALOSC_REMOVE, device_id)

    def _drain_notify(self, address: str, device_id: str) -> None:
        with self._notify_lock:
            subs = list(self._notify_subscribers)
            self._notify_subscribers.clear()
        for host, port in subs:
            self._endpoint.send(host, port, address, device_id)
        if subs:
            log.debug("notified %d subscriber(s): %s %s", len(subs), address, device_id)
