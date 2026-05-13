"""Application bootstrap.

Phase 2: starts the BridgeManager (serialosc discovery + per-device OSC
servers) and runs until interrupted. Phase 3 will replace the wait loop
with the Qt event loop.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from typing import Sequence

from . import __version__
from .config import AppConfig, DeviceProfileStore
from .log import configure_logging
from .serialosc import BridgeManager


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="monomepybridge",
        description="Standalone bridge for monome grid controllers (40h kit + serialosc-compatible).",
    )
    p.add_argument("--no-gui", action="store_true",
                   help="Run headless (no Qt GUI). Default for now.")
    p.add_argument("--once", action="store_true",
                   help="Start the bridge, list devices once, then exit.")
    p.add_argument("--log-level", default=None,
                   help="DEBUG / INFO / WARNING / ERROR (overrides config).")
    return p.parse_args(list(argv[1:]))


def run_app(argv: Sequence[str]) -> int:
    args = _parse_args(argv)
    cfg = AppConfig.load()
    level = getattr(logging, (args.log_level or cfg.log_level).upper(), logging.INFO)
    log = configure_logging(level=level)
    log.info("MonomePyBridge %s starting", __version__)

    profiles = DeviceProfileStore.load()
    log.info("Loaded %d device profile(s)", len(profiles.profiles))

    manager = BridgeManager(app_config=cfg, profile_store=profiles)
    manager.start()
    log.info("serialoscd advertised on UDP %d", cfg.osc_serialoscd_port)

    if args.once:
        time.sleep(0.5)
        slots = manager.list_slots()
        if slots:
            log.info("Active devices:")
            for s in slots:
                log.info("  %s [%s] listen=%d -> %s:%d prefix=%s",
                         s.device.id, s.device.info.type_name,
                         s.server.listen_port, s.server.host,
                         s.server.app_port, s.server.prefix)
        else:
            log.info("No devices attached.")
        manager.stop()
        return 0

    stop_evt = threading.Event()

    def _on_signal(signum, _frame):
        log.info("signal %d received — shutting down", signum)
        stop_evt.set()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _on_signal)
            except (ValueError, OSError):
                pass

    log.info("Running. Press Ctrl+C to stop.")
    try:
        while not stop_evt.is_set():
            stop_evt.wait(timeout=1.0)
    finally:
        manager.stop()
    return 0
