"""Interactive LED grid widget.

Displays a ``width × height`` matrix of cells (brightness 0-15) and
forwards mouse-press / mouse-release events to a callback. Used by the
device test panel to:

* show LED state being driven by the user's app over OSC,
* let the user inject synthetic button presses into a virtual grid, or
* paint LEDs directly on a physical device for testing.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget


CellCallback = Callable[[int, int, int], None]   # (x, y, state 0|1)


class GridWidget(QWidget):
    """Resizable LED grid. Brightness is 0-15."""

    cellPressed = Signal(int, int)        # (x, y)
    cellReleased = Signal(int, int)       # (x, y)

    def __init__(self, width_cells: int = 8, height_cells: int = 8,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._w = width_cells
        self._h = height_cells
        self._levels: list[list[int]] = [[0] * width_cells for _ in range(height_cells)]
        self._press_flash: dict[tuple[int, int], int] = {}  # (x,y) -> 0|1
        self.setMinimumSize(160, 160)
        self.setMouseTracking(False)

    # ── geometry ─────────────────────────────────────────────────────────
    def resize_grid(self, width_cells: int, height_cells: int) -> None:
        self._w = width_cells
        self._h = height_cells
        self._levels = [[0] * width_cells for _ in range(height_cells)]
        self._press_flash.clear()
        self.update()

    @property
    def cells_wide(self) -> int:
        return self._w

    @property
    def cells_high(self) -> int:
        return self._h

    # ── LED state input (from device side) ───────────────────────────────
    def set_level(self, x: int, y: int, level: int) -> None:
        if 0 <= x < self._w and 0 <= y < self._h:
            self._levels[y][x] = max(0, min(15, level))
            self.update()

    def set_all(self, level: int) -> None:
        lvl = max(0, min(15, level))
        for y in range(self._h):
            for x in range(self._w):
                self._levels[y][x] = lvl
        self.update()

    def set_snapshot(self, levels: list[list[int]]) -> None:
        for y in range(min(self._h, len(levels))):
            row = levels[y]
            for x in range(min(self._w, len(row))):
                self._levels[y][x] = max(0, min(15, row[x]))
        self.update()

    # ── press flash (from device hardware events) ────────────────────────
    def flash_key(self, x: int, y: int, state: int) -> None:
        key = (x, y)
        if state:
            self._press_flash[key] = 1
        else:
            self._press_flash.pop(key, None)
        self.update()

    # ── painting ─────────────────────────────────────────────────────────
    def _cell_rect(self, x: int, y: int, cell_size: int, ox: int, oy: int) -> QRect:
        return QRect(ox + x * cell_size + 1, oy + y * cell_size + 1,
                     cell_size - 2, cell_size - 2)

    def paintEvent(self, _event: QPaintEvent) -> None:
        if self._w <= 0 or self._h <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = self.rect()
        cell_size = max(8, min(rect.width() // self._w, rect.height() // self._h))
        grid_w = cell_size * self._w
        grid_h = cell_size * self._h
        ox = (rect.width() - grid_w) // 2
        oy = (rect.height() - grid_h) // 2

        # Background panel
        p.fillRect(QRect(ox, oy, grid_w, grid_h), QColor(20, 20, 20))

        for y in range(self._h):
            for x in range(self._w):
                lvl = self._levels[y][x]
                pressed = (x, y) in self._press_flash
                if pressed:
                    color = QColor(255, 80, 60)
                else:
                    intensity = int(40 + lvl * (215 / 15))
                    color = QColor(intensity, intensity // 3, 0) if lvl > 0 \
                        else QColor(35, 35, 35)
                p.fillRect(self._cell_rect(x, y, cell_size, ox, oy), color)

    # ── mouse → press/release ────────────────────────────────────────────
    def _xy_for_pos(self, pos) -> Optional[tuple[int, int]]:
        rect = self.rect()
        cell_size = max(8, min(rect.width() // self._w, rect.height() // self._h))
        grid_w = cell_size * self._w
        grid_h = cell_size * self._h
        ox = (rect.width() - grid_w) // 2
        oy = (rect.height() - grid_h) // 2
        gx = (pos.x() - ox) // cell_size
        gy = (pos.y() - oy) // cell_size
        if 0 <= gx < self._w and 0 <= gy < self._h:
            return int(gx), int(gy)
        return None

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        cell = self._xy_for_pos(ev.position().toPoint())
        if cell is not None:
            self.cellPressed.emit(*cell)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        cell = self._xy_for_pos(ev.position().toPoint())
        if cell is not None:
            self.cellReleased.emit(*cell)
