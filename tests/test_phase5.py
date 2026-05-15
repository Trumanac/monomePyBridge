"""Phase 5: MIDI + WebSocket bridges + persistent virtual grid."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from monomepybridge import paths as paths_mod
from monomepybridge.bridge.devices.virtual import VirtualGridDevice
from monomepybridge.bridges.midi_bridge import (
    MidiBridge, coord_to_note, note_to_coord,
)
from monomepybridge.bridges.ws_bridge import WebSocketBridge
from monomepybridge.config import AppConfig, DeviceProfileStore
from monomepybridge.discovery.scanner import DeviceScanner
from monomepybridge.serialosc.manager import BridgeManager


# ── tmp_paths fixture (same idea as Phase 4) ───────────────────────────

@pytest.fixture
def tmp_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(paths_mod, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(paths_mod, "log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(paths_mod, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(paths_mod, "config_file", lambda: tmp_path / "config.json")
    monkeypatch.setattr(paths_mod, "devices_file", lambda: tmp_path / "devices.json")
    yield tmp_path


# ── MIDI: pure coordinate-mapping math (no real MIDI port) ─────────────

def test_coord_note_roundtrip_8x8():
    base = 36
    for y in range(8):
        for x in range(8):
            n = coord_to_note(x, y, 8, base)
            assert note_to_coord(n, 8, 8, base) == (x, y)


def test_coord_note_oob():
    assert note_to_coord(35, 8, 8, 36) is None    # below base
    assert note_to_coord(36 + 64, 8, 8, 36) is None  # past last cell


def test_midi_bridge_no_ports_does_not_crash(monkeypatch):
    """If rtmidi has no ports + can't open virtual, start() must be a no-op."""
    import monomepybridge.bridges.midi_bridge as mb

    class _FakeRtMidiOut:
        def get_ports(self): return []
        def open_port(self, _i): raise AssertionError("should not be called")
        def open_virtual_port(self, _n): raise RuntimeError("no virtual ports here")
        def send_message(self, _m): pass
        def close_port(self): pass

    class _FakeRtMidiIn(_FakeRtMidiOut):
        def set_callback(self, _cb): pass

    class _FakeRtMidi:
        MidiOut = _FakeRtMidiOut
        MidiIn = _FakeRtMidiIn

    # Force Windows codepath ("no virtual ports") + no real ports available.
    monkeypatch.setattr(mb, "platform", type("P", (), {"system": staticmethod(lambda: "Windows")}))
    import sys
    monkeypatch.setitem(sys.modules, "rtmidi", _FakeRtMidi)

    dev = VirtualGridDevice("midi-test", 8, 8)
    dev.start()
    try:
        bridge = MidiBridge(dev)
        bridge.start()              # must not raise
        bridge.stop()
    finally:
        dev.stop()


# ── WebSocket bridge: end-to-end via real localhost socket ─────────────

def _ws_client_roundtrip(port: int, dev=None) -> dict:
    """Connect, read hello, send led_set, request a key event back, close."""
    import websockets

    captured: dict = {}

    async def run() -> None:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            captured["hello"] = hello
            # Drive an LED.
            await ws.send(json.dumps({"type": "led_set", "x": 3, "y": 4, "level": 12}))
            # Wait for the server to apply it (round-trip is async).
            await asyncio.sleep(0.1)
            # Capture LED state *before* the connection closes; the bridge
            # clears all LEDs on last-client-disconnect, so checking afterwards
            # would always return 0.
            if dev is not None:
                captured["led_3_4"] = dev.get_led(3, 4)

    asyncio.run(run())
    return captured


def test_websocket_bridge_hello_and_led():
    dev = VirtualGridDevice("ws-test", 8, 8)
    dev.start()
    bridge = WebSocketBridge(dev, host="127.0.0.1", port=0)
    bridge.start()
    try:
        assert bridge.port > 0
        result = _ws_client_roundtrip(bridge.port, dev)
        assert result["hello"]["type"] == "hello"
        assert result["hello"]["id"] == "ws-test"
        assert result["hello"]["width"] == 8
        # LED command should have landed on the virtual device.
        assert result["led_3_4"] == 12
    finally:
        bridge.stop()
        dev.stop()


def test_websocket_bridge_emits_key_event():
    dev = VirtualGridDevice("ws-key", 8, 8)
    dev.start()
    bridge = WebSocketBridge(dev, host="127.0.0.1", port=0)
    bridge.start()
    try:
        port = bridge.port
        captured: list[dict] = []

        async def run() -> None:
            import websockets
            async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                _hello = await asyncio.wait_for(ws.recv(), timeout=2.0)
                # Trigger a synthetic key from another thread.
                threading.Timer(0.05, lambda: dev.press(2, 1)).start()
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                captured.append(json.loads(msg))

        asyncio.run(run())
        assert captured, "expected a key event over WS"
        assert captured[0]["type"] == "key"
        assert captured[0]["x"] == 2
        assert captured[0]["y"] == 1
        assert captured[0]["s"] == 1
    finally:
        bridge.stop()
        dev.stop()


# ── Persistent virtual grid auto-attach ────────────────────────────────

def test_persistent_virtual_auto_attaches_on_start(tmp_paths):
    # Pre-seed a profile flagged as persistent virtual.
    store = DeviceProfileStore.load()
    p = store.get_or_create("virt-persist")
    p.virtual = True
    p.virtual_width = 16
    p.virtual_height = 8
    store.save()

    cfg = AppConfig.load()
    cfg.osc_serialoscd_port = 0
    profiles = DeviceProfileStore.load()
    scanner = DeviceScanner(poll_interval=10.0)
    mgr = BridgeManager(app_config=cfg, profile_store=profiles, scanner=scanner)
    mgr.start()
    try:
        # Give the auto-attach a tick.
        time.sleep(0.05)
        slot = mgr.find_slot("virt-persist")
        assert slot is not None
        assert slot.device.width == 16
        assert slot.device.height == 8
    finally:
        mgr.stop()


# ── Manager toggles for MIDI / WS / persistent ─────────────────────────

def test_manager_websocket_toggle_starts_and_stops(tmp_paths):
    cfg = AppConfig.load()
    cfg.osc_serialoscd_port = 0
    profiles = DeviceProfileStore.load()
    scanner = DeviceScanner(poll_interval=10.0)
    mgr = BridgeManager(app_config=cfg, profile_store=profiles, scanner=scanner)
    mgr.start()
    try:
        slot = mgr.attach_virtual_grid("virt-ws", 8, 8)
        # websocket_enabled defaults to True; disable first to establish a
        # known-off baseline before exercising the toggle logic.
        mgr.set_websocket_enabled(slot.device.id, False)
        assert slot.ws is None
        mgr.set_websocket_enabled(slot.device.id, True)
        assert slot.ws is not None
        assert slot.ws.port > 0
        # And the port should now be persisted on the profile.
        assert slot.profile.websocket_port == slot.ws.port
        mgr.set_websocket_enabled(slot.device.id, False)
        assert slot.ws is None
    finally:
        mgr.stop()
