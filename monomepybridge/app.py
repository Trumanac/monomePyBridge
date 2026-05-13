"""Application bootstrap.

Phase 0 stub: wires logging + config and prints a banner. The Qt GUI is
introduced in Phase 3.
"""

from __future__ import annotations

import logging
from typing import Sequence

from . import __version__
from .config import AppConfig, DeviceProfileStore
from .log import configure_logging


def run_app(argv: Sequence[str]) -> int:
    cfg = AppConfig.load()
    log = configure_logging(level=getattr(logging, cfg.log_level.upper(), logging.INFO))
    log.info("MonomePyBridge %s starting", __version__)
    log.info("Config loaded: serialoscd port=%d", cfg.osc_serialoscd_port)

    store = DeviceProfileStore.load()
    log.info("Loaded %d device profile(s)", len(store.profiles))

    # Phase 3 will replace this with the Qt GUI event loop.
    log.info("GUI not yet implemented — exiting (Phase 0 skeleton).")
    return 0
