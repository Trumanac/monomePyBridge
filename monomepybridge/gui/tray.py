"""System tray icon for MonomePyBridge."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .icons import app_icon


class TrayIcon(QObject):
    def __init__(
        self,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._on_show = on_show
        self._on_quit = on_quit
        self.icon = QSystemTrayIcon(app_icon(), parent)
        self.icon.setToolTip("MonomePyBridge")
        menu = QMenu()
        act_show = QAction("Show window", menu)
        act_show.triggered.connect(on_show)
        menu.addAction(act_show)
        menu.addSeparator()
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(on_quit)
        menu.addAction(act_quit)
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_show()
