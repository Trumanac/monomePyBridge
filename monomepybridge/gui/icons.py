"""Load the bundled app icon as a multi-resolution QIcon / QPixmap."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

_RESOURCES = Path(__file__).resolve().parent.parent / "resources"

# Sizes baked into the PNG set by scripts/make_icons.py
_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)


def app_icon() -> QIcon:
    """Return a QIcon populated with every bundled PNG size."""
    icon = QIcon()
    for s in _SIZES:
        p = _RESOURCES / f"icon_{s}.png"
        if p.exists():
            icon.addPixmap(QPixmap(str(p)))
    return icon


def app_pixmap(size: int = 256) -> QPixmap:
    """Return a QPixmap at *size* × *size* pixels (smooth-scaled from the best source)."""
    # Prefer the exact size, then the next size up, then the largest available.
    candidates = sorted((s for s in _SIZES if s >= size), key=lambda x: x)
    if not candidates:
        candidates = [max(_SIZES)]
    for s in candidates:
        p = _RESOURCES / f"icon_{s}.png"
        if p.exists():
            pix = QPixmap(str(p))
            if not pix.isNull():
                if s != size:
                    pix = pix.scaled(
                        size, size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                return pix
    return QPixmap()
