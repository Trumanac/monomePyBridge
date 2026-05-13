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
from ..bridges.midi_bridge import MidiBridge
from ..bridges.ws_bridge import WebSocketBridge
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
    midi: Optional[MidiBridge] = None
    ws: Optional[WebSocketBridge] = None


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
        self._auto_attach_persistent_virtuals()

    def _auto_attach_persistent_virtuals(self) -> None:
        """Re-create any virtual grids the user marked persistent."""
        for serial, prof in list(self.profiles.profiles.items()):
            if not getattr(prof, "virtual", False):
                continue
            if serial in self._slots:
                continue
            try:
                self.attach_virtual_grid(
                    serial_id=serial,
                    width=prof.virtual_width or 8,
                    height=prof.virtual_height or 8,
                )
            except Exception:
                log.exception("auto-attach virtual %s failed", serial)

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
            self._stop_optional_bridges(slot)
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
        self._apply_optional_bridges(slot)
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
        self._stop_optional_bridges(slot)
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

    def forget_device(self, serial: str) -> bool:
        """Detach a device (if attached) and remove its saved profile."""
        self._detach(serial)
        removed = self.profiles.remove(serial)
        if removed:
            self.profiles.save()
        return removed

    def restart_discovery(self) -> None:
        """Tear down + restart the serialoscd UDP listener (after port change)."""
        if self._discovery is not None:
            try:
                self._discovery.stop()
            except Exception:
                log.exception("discovery stop failed")
            self._discovery = None
        self._discovery = DiscoveryServer(
            device_provider=self._provide_devices,
            port=self.config.osc_serialoscd_port,
        )
        self._discovery.start()
        log.info("serialoscd restarted on UDP %d", self.config.osc_serialoscd_port)

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
        self._apply_optional_bridges(slot)
        log.info("attached virtual grid %s on listen=%d", device.id, server.listen_port)
        if self._discovery is not None:
            self._discovery.broadcast_add(device.id)
        self._notify_listeners()
        return slot

    # ── optional bridges (MIDI, WebSocket) ───────────────────────────────
    def _apply_optional_bridges(self, slot: _Slot) -> None:
        prof = slot.profile
        if prof.midi_enabled and slot.midi is None:
            try:
                slot.midi = MidiBridge(
                    slot.device,
                    channel=prof.midi_channel,
                    base_note=prof.midi_base_note,
                )
                slot.midi.start()
            except Exception:
                log.exception("MIDI bridge init failed for %s", slot.device.id)
                slot.midi = None
        if prof.websocket_enabled and slot.ws is None:
            try:
                slot.ws = WebSocketBridge(
                    slot.device, host="0.0.0.0",
                    port=prof.websocket_port or 0,
                )
                slot.ws.start()
                if slot.ws.port and prof.websocket_port == 0:
                    prof.websocket_port = slot.ws.port
                    self.profiles.save()
            except Exception:
                log.exception("WebSocket bridge init failed for %s", slot.device.id)
                slot.ws = None

    def _stop_optional_bridges(self, slot: _Slot) -> None:
        for attr in ("midi", "ws"):
            obj = getattr(slot, attr, None)
            if obj is not None:
                try:
                    obj.stop()
                except Exception:
                    log.exception("%s.stop() failed for %s", attr, slot.device.id)
                setattr(slot, attr, None)

    def set_midi_enabled(self, serial: str, enabled: bool) -> None:
        slot = self.find_slot(serial)
        if slot is None:
            return
        slot.profile.midi_enabled = bool(enabled)
        if enabled and slot.midi is None:
            self._apply_optional_bridges(slot)
        elif not enabled and slot.midi is not None:
            try:
                slot.midi.stop()
            finally:
                slot.midi = None
        self.profiles.save()

    def set_websocket_enabled(self, serial: str, enabled: bool) -> None:
        slot = self.find_slot(serial)
        if slot is None:
            return
        slot.profile.websocket_enabled = bool(enabled)
        if enabled and slot.ws is None:
            self._apply_optional_bridges(slot)
        elif not enabled and slot.ws is not None:
            try:
                slot.ws.stop()
            finally:
                slot.ws = None
        self.profiles.save()

    def set_persistent_virtual(self, serial: str, persistent: bool) -> None:
        prof = self.profiles.profiles.get(serial)
        if prof is None:
            return
        prof.virtual = bool(persistent)
        slot = self.find_slot(serial)
        if slot is not None:
            prof.virtual_width = slot.device.width
            prof.virtual_height = slot.device.height
        self.profiles.save()

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
