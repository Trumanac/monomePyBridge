"""GUI bootstrap: wires QApplication, MainWindow, tray, and the bridge."""

from __future__ import annotations

import logging
import sys
from typing import Optional, Sequence

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from ..config import AppConfig, DeviceProfileStore
from ..serialosc.manager import BridgeManager
from .icons import app_icon
from .log_handler import install_qt_log_bridge
from .main_window import MainWindow
from .qt_bridge import QtBridge
from .tray import TrayIcon

log = logging.getLogger("monomepybridge")


def run_gui(
    manager: BridgeManager,
    config: AppConfig,
    profiles: DeviceProfileStore,
    argv: Optional[Sequence[str]] = None,
) -> int:
    """Run the Qt event loop. Returns the app exit code."""
    qt_argv = list(argv) if argv is not None else sys.argv
    qapp = QApplication.instance() or QApplication(qt_argv)
    qapp.setApplicationName("MonomePyBridge")
    qapp.setOrganizationName("Trumanac")
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(app_icon())

    level_name = (config.log_level or "INFO").upper()
    bridge_level = getattr(logging, level_name, logging.INFO)
    if not isinstance(bridge_level, int):
        bridge_level = logging.INFO
    log_bridge = install_qt_log_bridge(level=bridge_level)
    qt_bridge = QtBridge(manager)

    win = MainWindow(qt_bridge, config, profiles, log_bridge)

    tray: Optional[TrayIcon] = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        def _show() -> None:
            win.showNormal()
            win.raise_()
            win.activateWindow()

        def _quit() -> None:
            win.request_quit()  # also calls qapp.quit() internally

        tray = TrayIcon(on_show=_show, on_quit=_quit)
        tray.show()
        win._has_tray = True  # noqa: SLF001

    if not config.start_minimized:
        win.show()

    def _shutdown() -> None:
        try:
            qt_bridge.shutdown()
        except Exception:
            pass
        try:
            manager.stop()
        except Exception:
            log.exception("manager.stop failed")
        if tray is not None:
            tray.hide()

    qapp.aboutToQuit.connect(_shutdown)

    # Periodically refresh status / device-list metadata (cheap).
    # Stored on qapp so it isn't garbage-collected before the event loop exits.
    qapp._refresh_timer = QTimer()  # noqa: SLF001
    qapp._refresh_timer.setInterval(2000)  # noqa: SLF001
    qapp._refresh_timer.timeout.connect(lambda: win._update_status())  # noqa: SLF001
    qapp._refresh_timer.start()  # noqa: SLF001

    return qapp.exec()
