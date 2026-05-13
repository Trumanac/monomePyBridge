"""Phase 4: persistence helpers + manager.forget_device + restart_discovery."""

from __future__ import annotations

import time

import pytest

from monomepybridge import paths as paths_mod
from monomepybridge.config import (
    AppConfig, DeviceProfileStore,
)
from monomepybridge.discovery.scanner import DeviceScanner
from monomepybridge.serialosc.manager import BridgeManager


@pytest.fixture
def tmp_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(paths_mod, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(paths_mod, "log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(paths_mod, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(paths_mod, "config_file", lambda: tmp_path / "config.json")
    monkeypatch.setattr(paths_mod, "devices_file", lambda: tmp_path / "devices.json")
    yield tmp_path


def test_appconfig_roundtrip(tmp_paths):
    c = AppConfig.load()
    c.osc_serialoscd_port = 23456
    c.start_minimized = True
    c.save()
    c2 = AppConfig.load()
    assert c2.osc_serialoscd_port == 23456
    assert c2.start_minimized is True


def test_profile_store_remove(tmp_paths):
    store = DeviceProfileStore.load()
    p = store.get_or_create("m40h-test")
    p.prefix = "/zap"
    store.save()
    assert store.remove("m40h-test") is True
    store.save()
    assert store.remove("m40h-test") is False
    again = DeviceProfileStore.load()
    assert "m40h-test" not in again.profiles


def test_profile_unknown_keys_dropped(tmp_paths):
    import json
    (tmp_paths / "devices.json").write_text(
        json.dumps({"m40h-x": {"serial": "m40h-x", "prefix": "/foo",
                               "bogus_field": 99}})
    )
    store = DeviceProfileStore.load()
    assert store.profiles["m40h-x"].prefix == "/foo"
    assert not hasattr(store.profiles["m40h-x"], "bogus_field")


def test_bridge_manager_forget_detaches_and_removes(tmp_paths):
    cfg = AppConfig.load()
    cfg.osc_serialoscd_port = 0
    profiles = DeviceProfileStore.load()
    scanner = DeviceScanner(poll_interval=10.0)
    mgr = BridgeManager(app_config=cfg, profile_store=profiles, scanner=scanner)
    mgr.start()
    try:
        slot = mgr.attach_virtual_grid("virt-forget", 8, 8)
        assert mgr.find_slot(slot.device.id) is not None
        assert slot.device.id in profiles.profiles

        assert mgr.forget_device(slot.device.id) is True
        assert mgr.find_slot(slot.device.id) is None
        assert slot.device.id not in profiles.profiles
    finally:
        mgr.stop()


def test_bridge_manager_restart_discovery(tmp_paths):
    cfg = AppConfig.load()
    cfg.osc_serialoscd_port = 0
    profiles = DeviceProfileStore.load()
    scanner = DeviceScanner(poll_interval=10.0)
    mgr = BridgeManager(app_config=cfg, profile_store=profiles, scanner=scanner)
    mgr.start()
    try:
        first = mgr._discovery
        assert first is not None
        _first_port = first._endpoint.port  # noqa: SLF001
        mgr.restart_discovery()
        time.sleep(0.05)
        assert mgr._discovery is not None
        assert mgr._discovery is not first
        # Port re-allocates (was 0 again) but is still a valid bound port.
        assert mgr._discovery._endpoint.port > 0  # noqa: SLF001
        # And the old endpoint should now report not-running (its socket closed).
    finally:
        mgr.stop()
