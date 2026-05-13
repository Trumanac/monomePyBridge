"""A logging handler that funnels records into a Qt signal."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal


class QtLogBridge(QObject):
    """Emits ``recordReady(level_name, formatted_text)`` for every log record.

    Lives on the Qt main thread; the handler can post from any thread
    because Qt signal/slot is thread-safe with queued connections.
    """

    recordReady = Signal(str, str)


class _SignalHandler(logging.Handler):
    def __init__(self, bridge: QtLogBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            text = self.format(record)
        except Exception:
            return
        try:
            self._bridge.recordReady.emit(record.levelname, text)
        except RuntimeError:
            # Bridge has been deleted (Qt object gone) — ignore.
            pass


def install_qt_log_bridge(level: int = logging.INFO) -> QtLogBridge:
    """Attach a :class:`_SignalHandler` to the ``monomepybridge`` logger."""
    bridge = QtLogBridge()
    handler = _SignalHandler(bridge)
    handler.setLevel(level)
    logging.getLogger("monomepybridge").addHandler(handler)
    return bridge
