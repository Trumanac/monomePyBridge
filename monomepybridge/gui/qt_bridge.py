"""Qt adapter around :class:`BridgeManager`.

Translates worker-thread events from the bridge (device hot-plug, key
presses, tilt) into Qt signals that fan out to the GUI on the main
thread via auto/queued connections.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..bridge.base import DeviceCallbacks
from ..serialosc.manager import BridgeManager, _Slot


class QtBridge(QObject):
    """Wraps a running :class:`BridgeManager` for the GUI."""

    devicesChanged = Signal()
    keyEvent = Signal(str, int, int, int)        # serial, x, y, state
    tiltEvent = Signal(str, int, int, int, int)  # serial, n, x, y, z

    def __init__(self, manager: BridgeManager, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._observers: dict[str, DeviceCallbacks] = {}
        manager.add_listener(self._on_devices_changed)
        # Pick up any already-attached slots (virtual grids, races).
        self._on_devices_changed()

    # ── public API ───────────────────────────────────────────────────────
    @property
    def manager(self) -> BridgeManager:
        return self._manager

    def slots(self) -> list[_Slot]:
        return self._manager.list_slots()

    def shutdown(self) -> None:
        self._manager.remove_listener(self._on_devices_changed)
        for serial, cb in list(self._observers.items()):
            slot = self._manager.find_slot(serial)
            if slot is not None:
                slot.device.remove_observer(cb)
        self._observers.clear()

    # ── manager listener (worker thread) ─────────────────────────────────
    def _on_devices_changed(self) -> None:
        # Sync our per-device observers with the live slot set.
        live = {s.device.id: s for s in self._manager.list_slots()}
        # Remove observers for vanished devices.
        for serial in list(self._observers):
            if serial not in live:
                self._observers.pop(serial, None)
        # Add observers for newcomers.
        for serial, slot in live.items():
            if serial in self._observers:
                continue
            cb = DeviceCallbacks(
                on_key=lambda x, y, s, sn=serial: self.keyEvent.emit(sn, x, y, s),
                on_tilt=lambda n, x, y, z, sn=serial: self.tiltEvent.emit(sn, n, x, y, z),
            )
            slot.device.add_observer(cb)
            self._observers[serial] = cb
        self.devicesChanged.emit()
