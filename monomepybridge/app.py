"""Application bootstrap.

Phase 1 stub: wires logging + config and runs one synchronous device-
discovery pass, printing what it finds. The Qt GUI lands in Phase 3.
"""

from __future__ import annotations

import logging
from typing import Sequence

from . import __version__
from .config import AppConfig, DeviceProfileStore
from .discovery import list_serial_ports
from .log import configure_logging


def run_app(argv: Sequence[str]) -> int:
    cfg = AppConfig.load()
    log = configure_logging(level=getattr(logging, cfg.log_level.upper(), logging.INFO))
    log.info("MonomePyBridge %s starting", __version__)
    log.info("Config loaded: serialoscd port=%d", cfg.osc_serialoscd_port)

    store = DeviceProfileStore.load()
    log.info("Loaded %d device profile(s)", len(store.profiles))

    ports = list_serial_ports(include_unknown=False)
    if ports:
        log.info("Discovered %d candidate port(s):", len(ports))
        for p in ports:
            log.info(
                "  %s [%s, guess=%s] %s",
                p.device, p.tier.value, p.guessed_protocol.value, p.description,
            )
    else:
        log.info("No candidate monome devices found on serial bus.")

    log.info("GUI not yet implemented — exiting (Phase 1 skeleton).")
    return 0
