"""Main window for MonomePyBridge."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QStatusBar, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..config import AppConfig, DeviceProfileStore
from .device_panel import DevicePanel
from .log_handler import QtLogBridge
from .qt_bridge import QtBridge


class MainWindow(QMainWindow):
    """Top-level window: device list + per-device panel + log dock."""

    def __init__(
        self,
        bridge: QtBridge,
        config: AppConfig,
        profiles: DeviceProfileStore,
        log_bridge: QtLogBridge,
    ) -> None:
        super().__init__()
        self.setWindowTitle("MonomePyBridge")
        self.resize(1100, 720)

        self._bridge = bridge
        self._config = config
        self._profiles = profiles
        self._log_bridge = log_bridge
        self._allow_close = False

        self._build_ui()
        self._wire_signals()
        self._refresh_device_list()
        self._update_status()

    # ── ui ──────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        # Menu
        menu = self.menuBar()
        m_file = menu.addMenu("&File")
        act_quit = QAction("&Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self._on_quit)
        m_file.addAction(act_quit)

        m_dev = menu.addMenu("&Devices")
        act_virt = QAction("Add &virtual grid (8×8)", self)
        act_virt.triggered.connect(lambda: self._add_virtual(8, 8))
        m_dev.addAction(act_virt)
        act_virt2 = QAction("Add virtual grid (16×8)", self)
        act_virt2.triggered.connect(lambda: self._add_virtual(16, 8))
        m_dev.addAction(act_virt2)
        act_virt3 = QAction("Add virtual grid (16×16)", self)
        act_virt3.triggered.connect(lambda: self._add_virtual(16, 16))
        m_dev.addAction(act_virt3)

        m_help = menu.addMenu("&Help")
        act_about = QAction("&About", self)
        act_about.triggered.connect(self._on_about)
        m_help.addAction(act_about)

        # Central layout: splitter [ devices | panel ]
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # Left: device list + actions
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)
        lv.addWidget(QLabel("<b>Devices</b>"))
        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["Serial", "Type", "Listen", "→ App"])
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setMinimumWidth(320)
        lv.addWidget(self._tree, 1)

        btn_row = QHBoxLayout()
        self._btn_add_virt = QPushButton("Add virtual grid")
        btn_row.addWidget(self._btn_add_virt)
        btn_row.addStretch(1)
        lv.addLayout(btn_row)

        splitter.addWidget(left)

        # Right: device panel (top) + log (bottom)
        right = QSplitter(Qt.Orientation.Vertical)
        self._panel = DevicePanel(self._bridge.manager, self._profiles)
        right.addWidget(self._panel)

        # Log
        log_box = QWidget()
        lg = QVBoxLayout(log_box)
        lg.setContentsMargins(8, 4, 8, 8)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("<b>Log</b>"))
        self._btn_clear_log = QPushButton("Clear")
        self._btn_clear_log.setMaximumWidth(80)
        log_header.addStretch(1)
        log_header.addWidget(self._btn_clear_log)
        lg.addLayout(log_header)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)
        self._log_view.setStyleSheet(
            "QPlainTextEdit { background: #111; color: #ddd; "
            "font-family: Consolas, 'Courier New', monospace; font-size: 11px; }"
        )
        lg.addWidget(self._log_view, 1)
        right.addWidget(log_box)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 760])

        # Status bar
        self.setStatusBar(QStatusBar())

    def _wire_signals(self) -> None:
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._btn_add_virt.clicked.connect(lambda: self._add_virtual(8, 8))
        self._btn_clear_log.clicked.connect(self._log_view.clear)
        self._panel.profileSaved.connect(lambda _s: self._refresh_device_list())

        self._bridge.devicesChanged.connect(self._on_devices_changed)
        self._bridge.keyEvent.connect(self._on_key_event)
        self._bridge.tiltEvent.connect(self._on_tilt_event)
        self._log_bridge.recordReady.connect(self._on_log_record)

    # ── device list ─────────────────────────────────────────────────────
    def _selected_serial(self) -> Optional[str]:
        item = self._tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _on_devices_changed(self) -> None:
        self._refresh_device_list()
        self._update_status()

    def _refresh_device_list(self) -> None:
        keep = self._selected_serial()
        self._tree.blockSignals(True)
        self._tree.clear()
        for slot in self._bridge.slots():
            it = QTreeWidgetItem([
                slot.device.id,
                slot.device.info.type_name,
                str(slot.server.listen_port),
                f"{slot.server.host}:{slot.server.app_port}",
            ])
            it.setData(0, Qt.ItemDataRole.UserRole, slot.device.id)
            self._tree.addTopLevelItem(it)
            if slot.device.id == keep:
                self._tree.setCurrentItem(it)
        self._tree.blockSignals(False)
        if self._tree.currentItem() is None and self._tree.topLevelItemCount() > 0:
            self._tree.setCurrentItem(self._tree.topLevelItem(0))
        else:
            self._on_selection_changed(self._tree.currentItem(), None)

    def _on_selection_changed(self, current, _previous) -> None:
        if current is None:
            self._panel.show_slot(None)
            return
        serial = current.data(0, Qt.ItemDataRole.UserRole)
        slot = self._bridge.manager.find_slot(serial)
        self._panel.show_slot(slot)

    # ── live events from devices ────────────────────────────────────────
    def _on_key_event(self, serial: str, x: int, y: int, state: int) -> None:
        if serial == self._selected_serial():
            self._panel.on_key_event(x, y, state)

    def _on_tilt_event(self, serial: str, n: int, x: int, y: int, z: int) -> None:
        if serial == self._selected_serial():
            self._panel.on_tilt_event(n, x, y, z)

    # ── log ─────────────────────────────────────────────────────────────
    def _on_log_record(self, level: str, text: str) -> None:
        self._log_view.appendPlainText(text)

    # ── actions ─────────────────────────────────────────────────────────
    def _add_virtual(self, w: int, h: int) -> None:
        existing = {s.device.id for s in self._bridge.slots()}
        n = 1
        while f"virt-{n:04d}" in existing:
            n += 1
        try:
            self._bridge.manager.attach_virtual_grid(
                serial_id=f"virt-{n:04d}", width=w, height=h
            )
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Add virtual grid", str(e))

    def _on_about(self) -> None:
        from .. import __version__
        QMessageBox.about(self, "About MonomePyBridge",
                          f"<b>MonomePyBridge</b> {__version__}<br>"
                          "Standalone bridge for monome grid controllers.<br>"
                          "Cross-platform replacement / superset of monomeserial.")

    def _update_status(self) -> None:
        n = len(self._bridge.slots())
        self.statusBar().showMessage(
            f"serialoscd: UDP {self._config.osc_serialoscd_port}    "
            f"devices: {n}"
        )

    # ── close → minimize to tray ────────────────────────────────────────
    def request_quit(self) -> None:
        self._allow_close = True
        self.close()

    def _on_quit(self) -> None:
        self.request_quit()

    def closeEvent(self, ev: QCloseEvent) -> None:
        if self._allow_close or not self._config.minimize_to_tray:
            ev.accept()
            return
        ev.ignore()
        self.hide()
        QTimer.singleShot(0, lambda: self.statusBar().showMessage(
            "Minimized to tray. Right-click the tray icon to quit.", 4000))
