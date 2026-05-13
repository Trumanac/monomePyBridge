"""System tray icon for MonomePyBridge."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def _make_tray_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.fillRect(8, 8, 48, 48, QColor(35, 35, 35))
    for y in range(4):
        for x in range(4):
            p.fillRect(12 + x * 12, 12 + y * 12,
                       8, 8, QColor(255, 140, 0))
    p.end()
    return QIcon(pix)


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
        self.icon = QSystemTrayIcon(_make_tray_icon(), parent)
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
