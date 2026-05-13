"""App-level Settings dialog (edits AppConfig)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QLineEdit, QSpinBox, QVBoxLayout, QWidget,
)

from ..config import AppConfig


_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


class SettingsDialog(QDialog):
    """Edit :class:`AppConfig` interactively."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MonomePyBridge — Settings")
        self.setMinimumWidth(440)
        self._config = config
        self._build()
        self._load_from_config()

    def _build(self) -> None:
        root = QVBoxLayout(self)

        # ── OSC ───────────────────────────────────────────────────────
        gb_osc = QGroupBox("OSC")
        f_osc = QFormLayout(gb_osc)
        self._ed_default_host = QLineEdit()
        self._sp_serialoscd = QSpinBox()
        self._sp_serialoscd.setRange(1, 65535)
        self._sp_base_port = QSpinBox()
        self._sp_base_port.setRange(1, 65535)
        f_osc.addRow("Default app host", self._ed_default_host)
        f_osc.addRow("serialoscd port", self._sp_serialoscd)
        f_osc.addRow("Per-device base port", self._sp_base_port)
        root.addWidget(gb_osc)

        # ── Legacy monomeserial mode ─────────────────────────────────
        gb_legacy = QGroupBox("Legacy monomeserial mode")
        f_leg = QFormLayout(gb_legacy)
        self._cx_legacy = QCheckBox("Enable fixed-prefix monomeserial-style server")
        self._sp_leg_listen = QSpinBox()
        self._sp_leg_listen.setRange(1, 65535)
        self._sp_leg_send = QSpinBox()
        self._sp_leg_send.setRange(1, 65535)
        f_leg.addRow("", self._cx_legacy)
        f_leg.addRow("Legacy listen port", self._sp_leg_listen)
        f_leg.addRow("Legacy send port", self._sp_leg_send)
        root.addWidget(gb_legacy)

        # ── GUI / system ─────────────────────────────────────────────
        gb_gui = QGroupBox("GUI")
        f_gui = QFormLayout(gb_gui)
        self._cx_tray = QCheckBox("Minimize to system tray on close")
        self._cx_min = QCheckBox("Start minimized to tray")
        self._cb_log = QComboBox()
        self._cb_log.addItems(_LOG_LEVELS)
        f_gui.addRow("", self._cx_tray)
        f_gui.addRow("", self._cx_min)
        f_gui.addRow("Log level", self._cb_log)
        root.addWidget(gb_gui)

        # ── buttons ──────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _load_from_config(self) -> None:
        c = self._config
        self._ed_default_host.setText(c.osc_default_host)
        self._sp_serialoscd.setValue(c.osc_serialoscd_port)
        self._sp_base_port.setValue(c.osc_device_base_port)
        self._cx_legacy.setChecked(c.legacy_mode_enabled)
        self._sp_leg_listen.setValue(c.legacy_listen_port)
        self._sp_leg_send.setValue(c.legacy_send_port)
        self._cx_tray.setChecked(c.minimize_to_tray)
        self._cx_min.setChecked(c.start_minimized)
        idx = _LOG_LEVELS.index(c.log_level) if c.log_level in _LOG_LEVELS else 1
        self._cb_log.setCurrentIndex(idx)

    def apply_to_config(self) -> AppConfig:
        c = self._config
        c.osc_default_host = self._ed_default_host.text().strip() or "127.0.0.1"
        c.osc_serialoscd_port = int(self._sp_serialoscd.value())
        c.osc_device_base_port = int(self._sp_base_port.value())
        c.legacy_mode_enabled = bool(self._cx_legacy.isChecked())
        c.legacy_listen_port = int(self._sp_leg_listen.value())
        c.legacy_send_port = int(self._sp_leg_send.value())
        c.minimize_to_tray = bool(self._cx_tray.isChecked())
        c.start_minimized = bool(self._cx_min.isChecked())
        c.log_level = self._cb_log.currentText()
        c.save()
        return c
