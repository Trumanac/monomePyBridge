"""Offscreen Qt smoke test for the GUI: spin up everything, attach a virtual grid, quit."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from monomepybridge.config import AppConfig, DeviceProfileStore
from monomepybridge.serialosc import BridgeManager
from monomepybridge.gui import run_gui


def main() -> int:
    cfg = AppConfig.load()
    cfg.osc_serialoscd_port = 0  # don't bind 12002 in the smoke test
    cfg.minimize_to_tray = False
    profiles = DeviceProfileStore.load()
    mgr = BridgeManager(app_config=cfg, profile_store=profiles)
    mgr.start()
    mgr.attach_virtual_grid("virt-smoke", 8, 8)
    # QApplication must exist before any QTimer.
    qapp = QApplication.instance() or QApplication(["mpb-smoke"])
    QTimer.singleShot(2000, qapp.quit)
    rc = run_gui(mgr, cfg, profiles, argv=["mpb-smoke"])
    print("EXIT", rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
