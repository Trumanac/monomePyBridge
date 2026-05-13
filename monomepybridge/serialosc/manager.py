"""High-level orchestrator: discovery -> driver -> per-device OSC server.

The :class:`BridgeManager` is the single object the GUI / CLI talk to.
It owns:

* The :class:`DeviceScanner` that polls USB serial ports.
* A pool of live :class:`Device` instances (one per attached monome).
* A :class:`DeviceOscServer` per device on its own auto-allocated port.
* The :class:`DiscoveryServer` on UDP 12002 (or the configured port).
* The :class:`DeviceProfileStore` for persistent per-device prefs.

Hot-plug add / remove is fully wired: when the scanner reports a new
port it builds a driver, starts it, spins up an OSC server, applies the
saved profile, and broadcasts a ``/serialosc/add`` notification. Removal
does the inverse.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from .. import config as cfg_mod
from ..bridge import Device, build_device
from ..bridge.factory import build_device as _build_device  # noqa: F401  (re-export safety)
from ..discovery import DeviceScanner, DiscoveredPort
from .device_server import DeviceOscServer
from .discovery_server import AdvertisedDevice, DiscoveryServer

log = logging.getLogger("monomepybridge")


@dataclass
class _Slot:
    port: DiscoveredPort
    device: Device
    server: DeviceOscServer
    profile: cfg_mod.DeviceProfile


# Optional listener so the GUI can refresh its device list.
ManagerListener = Callable[[], None]


class BridgeManager:
    def __init__(
        self,
        app_config: Optional[cfg_mod.AppConfig] = None,
        profile_store: Optional[cfg_mod.DeviceProfileStore] = None,
        scanner: Optional[DeviceScanner] = None,
    ) -> None:
        self.config = app_config or cfg_mod.AppConfig.load()
        self.profiles = profile_store or cfg_mod.DeviceProfileStore.load()
        self._scanner = scanner or DeviceScanner(poll_interval=2.0)
        self._slots: dict[str, _Slot] = {}      # keyed by stable_id
        self._slots_lock = threading.RLock()
        self._discovery: Optional[DiscoveryServer] = None
        self._next_port_hint = self.config.osc_device_base_port
        self._listeners: list[ManagerListener] = []

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        self._discovery = DiscoveryServer(
            device_provider=self._provide_devices,
            port=self.config.osc_serialoscd_port,
        )
        self._discovery.start()
        self._scanner.set_callbacks(on_added=self._on_port_added,
                                    on_removed=self._on_port_removed)
        self._scanner.start()
        log.info("BridgeManager started.")

    def stop(self) -> None:
        log.info("BridgeManager stopping.")
        try:
            self._scanner.stop()
        except Exception:
            pass
        with self._slots_lock:
            slots = list(self._slots.values())
            self._slots.clear()
        for slot in slots:
            try:
                slot.server.stop()
            finally:
                try:
                    slot.device.stop()
                except Exception:
                    log.exception("device stop failed: %s", slot.device.id)
        if self._discovery is not None:
            self._discovery.stop()
            self._discovery = None

    # ── listeners (GUI hook) ─────────────────────────────────────────────
    def add_listener(self, fn: ManagerListener) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: ManagerListener) -> None:
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    def _notify_listeners(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                log.exception("manager listener failed")

    # ── discovery callbacks ──────────────────────────────────────────────
    def _on_port_added(self, port: DiscoveredPort) -> None:
        try:
            self._attach(port)
        except Exception:
            log.exception("attach failed for %s", port.device)

    def _on_port_removed(self, port: DiscoveredPort) -> None:
        try:
            self._detach(port.stable_id)
        except Exception:
            log.exception("detach failed for %s", port.stable_id)

    def _attach(self, port: DiscoveredPort) -> None:
        with self._slots_lock:
            if port.stable_id in self._slots:
                return
        device = build_device(port)
        if device is None:
            log.info("no driver available for %s (proto guess=%s)",
                     port.device, port.guessed_protocol.value)
            return
        try:
            device.start()
        except Exception:
            log.exception("device.start failed for %s", port.device)
            return

        profile = self.profiles.get_or_create(device.id)
        listen_port = profile.osc_listen_port or 0
        server = DeviceOscServer(
            device,
            prefix=profile.prefix,
            host=profile.osc_host,
            app_port=profile.osc_app_port,
            listen_port=listen_port,
        )
        server.start()
        # Persist auto-allocated listen port back to profile.
        if profile.osc_listen_port == 0:
            profile.osc_listen_port = server.listen_port
            self.profiles.save()
        if profile.tilt_enabled:
            try:
                device.tilt_set(0, 1)
            except Exception:
                log.exception("tilt enable failed for %s", device.id)
        try:
            device.set_intensity(profile.intensity)
        except Exception:
            pass
        try:
            device.set_rotation(profile.rotation)
        except Exception:
            pass

        slot = _Slot(port=port, device=device, server=server, profile=profile)
        with self._slots_lock:
            self._slots[port.stable_id] = slot
        log.info("attached %s on listen=%d, dest=%s:%d, prefix=%s",
                 device.id, server.listen_port, server.host, server.app_port, server.prefix)
        if self._discovery is not None:
            self._discovery.broadcast_add(device.id)
        self._notify_listeners()

    def _detach(self, stable_id: str) -> None:
        with self._slots_lock:
            slot = self._slots.pop(stable_id, None)
        if slot is None:
            return
        try:
            slot.server.stop()
        finally:
            try:
                slot.device.stop()
            except Exception:
                log.exception("device.stop failed for %s", slot.device.id)
        log.info("detached %s", slot.device.id)
        if self._discovery is not None:
            self._discovery.broadcast_remove(slot.device.id)
        self._notify_listeners()

    # ── public inspection (GUI uses this) ────────────────────────────────
    def list_slots(self) -> list[_Slot]:
        with self._slots_lock:
            return list(self._slots.values())

    def find_slot(self, serial: str) -> Optional[_Slot]:
        with self._slots_lock:
            return self._slots.get(serial)

    def attach_virtual_grid(
        self,
        serial_id: str = "virt-0001",
        width: int = 8,
        height: int = 8,
    ) -> _Slot:
        """Inject an in-process :class:`VirtualGridDevice` (used by the GUI)."""
        from ..bridge.devices.virtual import VirtualGridDevice
        from ..discovery.scanner import (
            DiscoveredPort, GuessedProtocol, MatchTier,
        )
        device = VirtualGridDevice(serial_id=serial_id, width=width, height=height)
        device.start()

        profile = self.profiles.get_or_create(device.id)
        server = DeviceOscServer(
            device,
            prefix=profile.prefix,
            host=profile.osc_host,
            app_port=profile.osc_app_port,
            listen_port=profile.osc_listen_port or 0,
        )
        server.start()
        if profile.osc_listen_port == 0:
            profile.osc_listen_port = server.listen_port
            self.profiles.save()

        port = DiscoveredPort(
            device="virtual",
            serial_number=serial_id,
            description=device.info.type_name,
            manufacturer="MonomePyBridge",
            tier=MatchTier.MATCH_UNKNOWN,
            guessed_protocol=GuessedProtocol.PROTO_UNKNOWN,
        )
        slot = _Slot(port=port, device=device, server=server, profile=profile)
        with self._slots_lock:
            self._slots[serial_id] = slot
        log.info("attached virtual grid %s on listen=%d", device.id, server.listen_port)
        if self._discovery is not None:
            self._discovery.broadcast_add(device.id)
        self._notify_listeners()
        return slot

    def _provide_devices(self) -> list[AdvertisedDevice]:
        out: list[AdvertisedDevice] = []
        with self._slots_lock:
            for slot in self._slots.values():
                out.append(AdvertisedDevice(
                    id=slot.device.id,
                    type_name=slot.device.info.type_name,
                    port=slot.server.listen_port,
                ))
        return out
