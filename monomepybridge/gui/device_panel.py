"""Per-device editor + live test panel."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QPushButton, QSlider, QSpinBox, QVBoxLayout,
    QWidget,
)

from ..bridge.devices.virtual import VirtualGridDevice
from ..config import DeviceProfile, DeviceProfileStore
from ..osc.protocol import normalize_prefix
from ..serialosc.manager import BridgeManager, _Slot
from .grid_widget import GridWidget


class DevicePanel(QWidget):
    """Editor + live LED test for a single device slot."""

    profileSaved = Signal(str)   # serial

    def __init__(
        self,
        manager: BridgeManager,
        profiles: DeviceProfileStore,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._profiles = profiles
        self._slot: Optional[_Slot] = None
        self._build()

    # ── ui ──────────────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)

        # ── identity card ─────────────────────────────────────────────
        self._lbl_id = QLabel("(no device selected)")
        f = self._lbl_id.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 2)
        self._lbl_id.setFont(f)
        self._lbl_meta = QLabel("")
        self._lbl_meta.setStyleSheet("color: #888;")
        root.addWidget(self._lbl_id)
        root.addWidget(self._lbl_meta)

        # ── profile editor ────────────────────────────────────────────
        gb_cfg = QGroupBox("OSC profile")
        form = QFormLayout(gb_cfg)
        self._ed_prefix = QLineEdit()
        self._ed_host = QLineEdit()
        self._sp_app_port = QSpinBox()
        self._sp_app_port.setRange(1, 65535)
        self._sp_listen_port = QSpinBox()
        self._sp_listen_port.setRange(0, 65535)
        self._sp_listen_port.setReadOnly(True)
        self._sp_listen_port.setEnabled(False)
        self._cb_rotation = QComboBox()
        self._cb_rotation.addItems(["0°", "90°", "180°", "270°"])
        self._sl_intensity = QSlider(Qt.Orientation.Horizontal)
        self._sl_intensity.setRange(0, 15)
        self._sl_intensity.setTickInterval(1)
        self._sl_intensity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._cx_tilt = QCheckBox("Enable tilt streaming")
        self._cx_midi = QCheckBox("Enable MIDI bridge")
        self._sp_midi_ch = QSpinBox()
        self._sp_midi_ch.setRange(1, 16)
        self._sp_midi_base = QSpinBox()
        self._sp_midi_base.setRange(0, 127)
        self._cx_ws = QCheckBox("Enable WebSocket bridge")
        self._sp_ws_port = QSpinBox()
        self._sp_ws_port.setRange(0, 65535)
        self._lbl_ws_status = QLabel("")
        self._lbl_ws_status.setStyleSheet("color: #888;")
        self._btn_ws_demo = QPushButton("Open WebSocket Demo →")
        self._btn_ws_demo.setVisible(False)
        self._btn_ws_demo.setToolTip("Open ws_demo.html in your browser (pre-filled with this device's port)")
        self._btn_ws_demo.clicked.connect(self._on_open_ws_demo)
        self._cx_persist = QCheckBox("Persistent virtual grid (auto-attach at startup)")

        form.addRow("Prefix", self._ed_prefix)
        form.addRow("App host", self._ed_host)
        form.addRow("App port (out)", self._sp_app_port)
        form.addRow("Listen port (in)", self._sp_listen_port)
        form.addRow("Rotation", self._cb_rotation)
        form.addRow("Intensity", self._sl_intensity)
        form.addRow("", self._cx_tilt)
        form.addRow("", self._cx_midi)
        form.addRow("MIDI channel", self._sp_midi_ch)
        form.addRow("MIDI base note", self._sp_midi_base)
        form.addRow("", self._cx_ws)
        form.addRow("WebSocket port (0=auto)", self._sp_ws_port)
        form.addRow("", self._lbl_ws_status)
        form.addRow("", self._btn_ws_demo)
        form.addRow("", self._cx_persist)

        btn_row = QHBoxLayout()
        self._btn_save = QPushButton("Apply && save")
        self._btn_revert = QPushButton("Revert")
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_revert)
        btn_row.addStretch(1)
        form.addRow(btn_row)
        root.addWidget(gb_cfg)

        # ── live test ─────────────────────────────────────────────────
        gb_test = QGroupBox("Live test")
        v = QVBoxLayout(gb_test)
        self._grid = GridWidget(8, 8)
        v.addWidget(self._grid, 1)
        test_btns = QHBoxLayout()
        self._btn_test_all_on = QPushButton("All on")
        self._btn_test_all_off = QPushButton("All off")
        self._btn_test_chase = QPushButton("Chase")
        test_btns.addWidget(self._btn_test_all_on)
        test_btns.addWidget(self._btn_test_all_off)
        test_btns.addWidget(self._btn_test_chase)
        test_btns.addStretch(1)
        v.addLayout(test_btns)

        # tilt readout
        tilt_row = QHBoxLayout()
        self._pb_tilt_x = QProgressBar()
        self._pb_tilt_y = QProgressBar()
        self._pb_tilt_z = QProgressBar()
        for pb in (self._pb_tilt_x, self._pb_tilt_y, self._pb_tilt_z):
            pb.setRange(0, 255)
            pb.setTextVisible(True)
        tilt_row.addWidget(QLabel("Tilt"))
        tilt_row.addWidget(QLabel("X"))
        tilt_row.addWidget(self._pb_tilt_x)
        tilt_row.addWidget(QLabel("Y"))
        tilt_row.addWidget(self._pb_tilt_y)
        tilt_row.addWidget(QLabel("Z"))
        tilt_row.addWidget(self._pb_tilt_z)
        v.addLayout(tilt_row)

        root.addWidget(gb_test, 1)

        # ── signals ───────────────────────────────────────────────────
        self._btn_save.clicked.connect(self._on_save)
        self._btn_revert.clicked.connect(self._refresh_form)
        self._btn_test_all_on.clicked.connect(lambda: self._led_all(15))
        self._btn_test_all_off.clicked.connect(lambda: self._led_all(0))
        self._btn_test_chase.clicked.connect(self._test_chase)
        self._sl_intensity.valueChanged.connect(self._on_intensity_live)
        self._grid.cellPressed.connect(self._on_cell_pressed)
        self._grid.cellReleased.connect(self._on_cell_released)

        self._set_enabled(False)

    def _set_enabled(self, on: bool) -> None:
        for w in (
            self._ed_prefix, self._ed_host, self._sp_app_port, self._cb_rotation,
            self._sl_intensity, self._cx_tilt, self._cx_midi, self._sp_midi_ch,
            self._sp_midi_base, self._cx_ws, self._sp_ws_port, self._cx_persist,
            self._btn_save, self._btn_revert,
            self._btn_test_all_on, self._btn_test_all_off, self._btn_test_chase,
            self._grid,
        ):
            w.setEnabled(on)

    # ── slot binding ────────────────────────────────────────────────────
    def show_slot(self, slot: Optional[_Slot]) -> None:
        self._slot = slot
        if slot is None:
            self._lbl_id.setText("(no device selected)")
            self._lbl_meta.setText("")
            self._set_enabled(False)
            self._grid.resize_grid(8, 8)
            return
        info = slot.device.info
        self._lbl_id.setText(f"{info.serial}  —  {info.type_name}")
        self._lbl_meta.setText(
            f"transport: {info.transport or '?'}    "
            f"protocol: {info.protocol.value}    "
            f"size: {info.width}×{info.height}    "
            f"levels: {'yes' if info.supports_levels else 'binary only'}    "
            f"tilt: {'yes' if info.supports_tilt else 'no'}"
        )
        self._grid.resize_grid(info.width, info.height)
        if isinstance(slot.device, VirtualGridDevice):
            self._grid.set_snapshot(slot.device.snapshot())
        self._set_enabled(True)
        self._refresh_form()

    def _refresh_form(self) -> None:
        slot = self._slot
        if slot is None:
            return
        p = slot.profile
        self._ed_prefix.setText(p.prefix)
        self._ed_host.setText(p.osc_host)
        self._sp_app_port.setValue(p.osc_app_port)
        self._sp_listen_port.setValue(slot.server.listen_port)
        rot_idx = {0: 0, 90: 1, 180: 2, 270: 3}.get(p.rotation, 0)
        self._cb_rotation.setCurrentIndex(rot_idx)
        self._sl_intensity.blockSignals(True)
        self._sl_intensity.setValue(p.intensity)
        self._sl_intensity.blockSignals(False)
        self._cx_tilt.setChecked(p.tilt_enabled)
        self._cx_midi.setChecked(p.midi_enabled)
        self._sp_midi_ch.setValue(p.midi_channel)
        self._sp_midi_base.setValue(p.midi_base_note)
        self._cx_ws.setChecked(p.websocket_enabled)
        self._sp_ws_port.setValue(p.websocket_port)
        self._cx_persist.setChecked(getattr(p, "virtual", False))
        self._cx_persist.setVisible(
            slot.device.info.protocol.value == "virtual"
        )
        ws_port = slot.ws.port if slot.ws is not None else None
        self._lbl_ws_status.setText(
            f"WebSocket: ws://localhost:{ws_port}" if ws_port else ""
        )
        self._btn_ws_demo.setVisible(bool(ws_port))
        if ws_port:
            self._btn_ws_demo.setProperty("ws_port", ws_port)

    # ── editor actions ──────────────────────────────────────────────────
    def _on_open_ws_demo(self) -> None:
        demo = Path(__file__).parent.parent.parent / "tests" / "ws_demo.html"
        port = self._btn_ws_demo.property("ws_port") or 0
        url = QUrl.fromLocalFile(str(demo))
        if port:
            url.setQuery(f"port={port}")
        QDesktopServices.openUrl(url)

    def _on_save(self) -> None:
        slot = self._slot
        if slot is None:
            return
        p: DeviceProfile = slot.profile
        p.prefix = normalize_prefix(self._ed_prefix.text().strip())
        p.osc_host = self._ed_host.text().strip() or "127.0.0.1"
        p.osc_app_port = int(self._sp_app_port.value())
        p.rotation = [0, 90, 180, 270][self._cb_rotation.currentIndex()]
        p.intensity = int(self._sl_intensity.value())
        p.tilt_enabled = bool(self._cx_tilt.isChecked())
        # Push live to the running server + device.
        slot.server.update_destination(p.osc_host, p.osc_app_port)
        slot.server.set_prefix(p.prefix)
        try:
            slot.device.set_intensity(p.intensity)
        except Exception:
            pass
        try:
            slot.device.set_rotation(p.rotation)
        except Exception:
            pass
        try:
            slot.device.tilt_set(0, 1 if p.tilt_enabled else 0)
        except Exception:
            pass
        # Optional bridges: persist field values + apply via the manager so
        # the bridges actually start / stop.
        p.midi_channel = int(self._sp_midi_ch.value())
        p.midi_base_note = int(self._sp_midi_base.value())
        p.websocket_port = int(self._sp_ws_port.value())
        self._manager.set_midi_enabled(slot.device.id, bool(self._cx_midi.isChecked()))
        self._manager.set_websocket_enabled(slot.device.id, bool(self._cx_ws.isChecked()))
        if slot.device.info.protocol.value == "virtual":
            self._manager.set_persistent_virtual(
                slot.device.id, bool(self._cx_persist.isChecked())
            )
        self._profiles.save()
        self._refresh_form()
        self.profileSaved.emit(slot.device.id)

    def _on_intensity_live(self, value: int) -> None:
        if self._slot is None:
            return
        try:
            self._slot.device.set_intensity(int(value))
        except Exception:
            pass

    # ── live test actions ───────────────────────────────────────────────
    def _led_all(self, level: int) -> None:
        if self._slot is None:
            return
        try:
            self._slot.device.led_all(level)
        except Exception:
            pass
        self._grid.set_all(level)

    def _test_chase(self) -> None:
        slot = self._slot
        if slot is None:
            return
        # Light each LED briefly in a sweep — sync, simple.
        from PySide6.QtCore import QTimer
        cells = [(x, y) for y in range(slot.device.height)
                 for x in range(slot.device.width)]
        idx = {"i": 0}

        def step() -> None:
            if self._slot is not slot:
                return  # user switched device mid-chase; abandon silently
            if idx["i"] >= len(cells):
                self._led_all(0)
                return
            x, y = cells[idx["i"]]
            slot.device.led_set(x, y, 15)
            self._grid.set_level(x, y, 15)
            idx["i"] += 1
            QTimer.singleShot(20, step)

        self._led_all(0)
        QTimer.singleShot(0, step)

    # ── grid mouse → device ─────────────────────────────────────────────
    def _on_cell_pressed(self, x: int, y: int) -> None:
        slot = self._slot
        if slot is None:
            return
        # Toggle LED on the device, mirror locally.
        new_lvl = 0 if self._grid_get(x, y) > 0 else 15
        try:
            slot.device.led_set(x, y, new_lvl)
        except Exception:
            pass
        self._grid.set_level(x, y, new_lvl)
        # If virtual, also synthesize a press so users can feel the round-trip.
        if isinstance(slot.device, VirtualGridDevice):
            slot.device.press(x, y)

    def _on_cell_released(self, x: int, y: int) -> None:
        slot = self._slot
        if slot is None:
            return
        if isinstance(slot.device, VirtualGridDevice):
            slot.device.release(x, y)

    def _grid_get(self, x: int, y: int) -> int:
        # Read from the GridWidget's backing model via a small helper.
        try:
            return self._grid._levels[y][x]  # noqa: SLF001
        except (IndexError, AttributeError):
            return 0

    # ── inbound device events (called by main window) ───────────────────
    def on_key_event(self, x: int, y: int, state: int) -> None:
        self._grid.flash_key(x, y, state)

    def on_tilt_event(self, n: int, x: int, y: int, z: int) -> None:
        if n != 0:
            return
        self._pb_tilt_x.setValue(max(0, min(255, x)))
        self._pb_tilt_y.setValue(max(0, min(255, y)))
        self._pb_tilt_z.setValue(max(0, min(255, z)))
