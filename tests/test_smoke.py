"""Phase 0 smoke tests."""

from __future__ import annotations


def test_import_package() -> None:
    import monomepybridge

    assert monomepybridge.__version__


def test_config_roundtrip(tmp_path, monkeypatch) -> None:
    # Redirect platformdirs to a temp directory.
    from monomepybridge import config as cfg_mod
    from monomepybridge import paths as paths_mod

    monkeypatch.setattr(paths_mod, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(paths_mod, "config_file", lambda: tmp_path / "config.json")
    monkeypatch.setattr(paths_mod, "devices_file", lambda: tmp_path / "devices.json")

    c = cfg_mod.AppConfig.load()
    c.osc_serialoscd_port = 12345
    c.save()
    c2 = cfg_mod.AppConfig.load()
    assert c2.osc_serialoscd_port == 12345


def test_device_profile_store(tmp_path, monkeypatch) -> None:
    from monomepybridge import config as cfg_mod
    from monomepybridge import paths as paths_mod

    monkeypatch.setattr(paths_mod, "devices_file", lambda: tmp_path / "devices.json")
    monkeypatch.setattr(paths_mod, "config_dir", lambda: tmp_path)

    store = cfg_mod.DeviceProfileStore.load()
    p = store.get_or_create("m64-0858")
    p.prefix = "/40h"
    p.rotation = 90
    store.save()

    store2 = cfg_mod.DeviceProfileStore.load()
    assert store2.profiles["m64-0858"].prefix == "/40h"
    assert store2.profiles["m64-0858"].rotation == 90
