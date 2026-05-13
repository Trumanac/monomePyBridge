"""Logging setup for MonomePyBridge.

A single named logger ``monomepybridge`` is used across the app. The
:func:`configure_logging` helper installs a rotating file handler in
:func:`paths.log_dir` plus a console handler.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .paths import log_dir

LOGGER_NAME = "monomepybridge"

_LOG_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FMT = "%H:%M:%S"


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def configure_logging(level: int = logging.INFO, *, console: bool = True) -> logging.Logger:
    """Install handlers on the root MonomePyBridge logger. Idempotent."""
    log = logging.getLogger(LOGGER_NAME)
    log.setLevel(level)
    if getattr(log, "_mpb_configured", False):
        return log

    fmt = logging.Formatter(_LOG_FMT, datefmt=_DATE_FMT)

    file_handler = RotatingFileHandler(
        log_dir() / "monomepybridge.log",
        maxBytes=512_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        log.addHandler(console_handler)

    log.propagate = False
    log._mpb_configured = True  # type: ignore[attr-defined]
    return log
