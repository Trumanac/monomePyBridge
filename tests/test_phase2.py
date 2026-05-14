"""Phase 2 — OSC + serialosc tests.

Uses the in-process VirtualGridDevice + an ephemeral python-osc client
socket to exercise the full message round-trip without any hardware.
"""

from __future__ import annotations

import socket
import threading
import time

from pythonosc import udp_client
from pythonosc.osc_packet import OscPacket

from monomepybridge.bridge.devices.virtual import VirtualGridDevice
from monomepybridge.osc import protocol as P
from monomepybridge.osc.endpoint import build_osc_message
from monomepybridge.serialosc.device_server import DeviceOscServer
from monomepybridge.serialosc.discovery_server import (
    AdvertisedDevice,
    DiscoveryServer,
)


# ── helpers ─────────────────────────────────────────────────────────────

def _wait_for(predicate, timeout: float = 1.0, interval: float = 0.005):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class _UDPListener:
    """Tiny inline UDP listener used as the 'app' destination in tests."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.25)
        self.host, self.port = self.sock.getsockname()
        self.received: list[tuple[str, list]] = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except Exception:
            pass
        self._t.join(timeout=0.5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                pkt = OscPacket(data)
            except Exception:
                continue
            for tm in pkt.messages:
                self.received.append((tm.message.address, list(tm.message.params)))


# ── protocol helpers ────────────────────────────────────────────────────

def test_normalize_prefix():
    assert P.normalize_prefix("") == "/monome"
    assert P.normalize_prefix("monome") == "/monome"
    assert P.normalize_prefix("/40h/") == "/40h"
    assert P.normalize_prefix("/40h") == "/40h"


def test_row_mask_roundtrip():
    levels = [15, 0, 15, 15, 0, 0, 0, 15]
    mask = P.pack_row_mask(levels)
    expanded = P.expand_row_mask(mask)
    assert expanded == [15, 0, 15, 15, 0, 0, 0, 15]


def test_build_osc_message_roundtrip():
    dgram = build_osc_message("/sys/port", [12345])
    pkt = OscPacket(dgram)
    msg = pkt.messages[0].message
    assert msg.address == "/sys/port"
    assert list(msg.params) == [12345]


# ── DeviceOscServer ─────────────────────────────────────────────────────

def test_device_server_led_set_levels():
    dev = VirtualGridDevice()
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome", host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message("/monome/grid/led/level/set", [3, 4, 12])
        assert _wait_for(lambda: dev.get_led(3, 4) == 12)
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_device_server_led_all_binary():
    dev = VirtualGridDevice()
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome", host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message("/monome/grid/led/all", [1])
        assert _wait_for(lambda: all(v == 15 for row in dev.snapshot() for v in row))
        client.send_message("/monome/grid/led/all", [0])
        assert _wait_for(lambda: all(v == 0 for row in dev.snapshot() for v in row))
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_device_server_led_map_quadrant():
    dev = VirtualGridDevice()
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome", host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        # 8 row masks: every other LED on
        masks = [0xAA] * 8
        client.send_message("/monome/grid/led/map", [0, 0, *masks])
        def check():
            snap = dev.snapshot()
            for y in range(8):
                for x in range(8):
                    expected = 15 if (0xAA >> x) & 1 else 0
                    if snap[y][x] != expected:
                        return False
            return True
        assert _wait_for(check)
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_device_server_emits_key_event():
    dev = VirtualGridDevice()
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome", host=listener.host, app_port=listener.port)
    srv.start()
    try:
        dev.press(2, 3)
        dev.release(2, 3)
        assert _wait_for(lambda: len(listener.received) >= 2)
        addrs = [m[0] for m in listener.received]
        assert "/monome/grid/key" in addrs
        # Find the press event (state=1)
        press = [m for m in listener.received if m[0] == "/monome/grid/key" and m[1][2] == 1]
        assert press and press[0][1][:2] == [2, 3]
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_device_server_sys_info_replies():
    dev = VirtualGridDevice()
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome", host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message("/sys/info", [])
        assert _wait_for(lambda: len(listener.received) >= 5)
        addrs = {m[0] for m in listener.received}
        for required in ("/sys/id", "/sys/size", "/sys/host", "/sys/port",
                         "/sys/prefix", "/sys/rotation"):
            assert required in addrs, f"missing {required} in {addrs}"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_device_server_prefix_change_at_runtime():
    dev = VirtualGridDevice()
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome", host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message("/sys/prefix", ["/40h"])
        assert _wait_for(lambda: srv.prefix == "/40h")
        # Old prefix should no longer route.
        client.send_message("/monome/grid/led/all", [1])
        time.sleep(0.05)
        assert all(v == 0 for row in dev.snapshot() for v in row)
        # New prefix routes.
        client.send_message("/40h/grid/led/all", [1])
        assert _wait_for(lambda: all(v == 15 for row in dev.snapshot() for v in row))
    finally:
        srv.stop()
        listener.close()
        dev.stop()


# ── DiscoveryServer (UDP 12002 protocol) ────────────────────────────────

def test_discovery_list_replies_with_devices():
    devices = [
        AdvertisedDevice(id="m64-0858", type_name="monome 40h", port=15001),
        AdvertisedDevice(id="m128-0042", type_name="monome 128", port=15002),
    ]
    server = DiscoveryServer(device_provider=lambda: devices, port=0)
    server.start()
    listener = _UDPListener()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", server.port)
        client.send_message("/serialosc/list", [listener.host, listener.port])
        assert _wait_for(lambda: len(listener.received) >= 2)
        addrs = [m[0] for m in listener.received]
        assert addrs.count("/serialosc/device") == 2
        ids = [m[1][0] for m in listener.received]
        assert "m64-0858" in ids and "m128-0042" in ids
    finally:
        server.stop()
        listener.close()


def test_discovery_notify_one_shot_add_remove():
    server = DiscoveryServer(device_provider=lambda: [], port=0)
    server.start()
    listener = _UDPListener()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", server.port)
        client.send_message("/serialosc/notify", [listener.host, listener.port])
        # Give it a tick to register.
        time.sleep(0.05)
        server.broadcast_add("m64-NEW1")
        assert _wait_for(lambda: any(m[0] == "/serialosc/add" for m in listener.received))
        # Subscription is one-shot: a second event without re-subscribing should be silent.
        listener.received.clear()
        server.broadcast_remove("m64-NEW1")
        time.sleep(0.1)
        assert listener.received == []
        # Re-subscribe; remove should fire.
        client.send_message("/serialosc/notify", [listener.host, listener.port])
        time.sleep(0.05)
        server.broadcast_remove("m64-NEW1")
        assert _wait_for(lambda: any(m[0] == "/serialosc/remove" for m in listener.received))
    finally:
        server.stop()
        listener.close()


# ── End-to-end via BridgeManager + virtual device ───────────────────────

def test_bridge_manager_attaches_virtual_device(tmp_path, monkeypatch):
    """Plug the virtual device in 'manually' through the manager API."""
    from monomepybridge import config as cfg_mod
    from monomepybridge import paths as paths_mod
    from monomepybridge.discovery.scanner import (
        DiscoveredPort, MatchTier, GuessedProtocol,
    )
    from monomepybridge.serialosc.manager import BridgeManager

    monkeypatch.setattr(paths_mod, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(paths_mod, "config_file", lambda: tmp_path / "config.json")
    monkeypatch.setattr(paths_mod, "devices_file", lambda: tmp_path / "devices.json")

    # Bypass the scanner entirely by using port=0 for serialoscd and
    # injecting a custom factory that returns a virtual device.
    app_cfg = cfg_mod.AppConfig.load()
    app_cfg.osc_serialoscd_port = 0
    profiles = cfg_mod.DeviceProfileStore.load()

    # Prevent the background scanner from discovering real serial ports on
    # this machine (e.g. COM7) and racing with our manual _on_port_added call.
    import monomepybridge.discovery.scanner as scanner_mod
    monkeypatch.setattr(scanner_mod, "list_serial_ports", lambda **_kw: [])

    mgr = BridgeManager(app_config=app_cfg, profile_store=profiles)
    # Patch build_device used inside the manager module to always return
    # a fresh VirtualGridDevice — sidesteps real serial drivers.
    import monomepybridge.serialosc.manager as mgr_mod
    monkeypatch.setattr(mgr_mod, "build_device",
                        lambda port: VirtualGridDevice(serial_id=port.serial_number or "v-1"))
    mgr.start()
    try:
        fake_port = DiscoveredPort(
            device="VIRTUAL",
            serial_number="v-test-1",
            tier=MatchTier.MATCH_MONOME,
            guessed_protocol=GuessedProtocol.PROTO_40H,
        )
        mgr._on_port_added(fake_port)  # type: ignore[attr-defined]
        slots = mgr.list_slots()
        assert len(slots) == 1
        slot = slots[0]
        assert slot.device.id == "v-test-1"
        # Profile should now have the auto-allocated listen port persisted.
        prof = profiles.profiles["v-test-1"]
        assert prof.osc_listen_port == slot.server.listen_port

        mgr._on_port_removed(fake_port)  # type: ignore[attr-defined]
        assert mgr.list_slots() == []
    finally:
        mgr.stop()
