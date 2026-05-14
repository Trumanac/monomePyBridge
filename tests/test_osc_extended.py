"""Extended OSC tests.

Covers the parts of the serialosc surface not exercised by test_phase2.py:

* /sys/host + /sys/port destination redirect
* /sys/prefix live rewire
* /sys/rotation
* /sys/id and /sys/size queries
* /sys/info with explicit (host, port) target
* level variants: /grid/led/level/all, /row, /col, /map
* binary mask variants: /grid/led/row, /grid/led/col
* /grid/led/intensity
* tilt: event forwarded over OSC, /tilt/set accepted
* serialosc discovery: /serialosc/list response
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


# ── helpers ─────────────────────────────────────────────────────────────

def _wait_for(predicate, timeout: float = 1.5, interval: float = 0.005) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class _UDPListener:
    """Minimal UDP listener that collects OSC messages as (address, params) pairs."""

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

    def find(self, addr: str) -> list[tuple[str, list]]:
        return [m for m in self.received if m[0] == addr]


# ── /sys/host + /sys/port: redirect key events ──────────────────────────

def test_sys_host_port_change_redirects_key_events() -> None:
    """After /sys/host + /sys/port, key events land at the new destination."""
    dev = VirtualGridDevice("redir-test", 8, 8)
    dev.start()
    listener1 = _UDPListener()
    listener2 = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener1.host, app_port=listener1.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        # Redirect destination to listener2
        client.send_message(P.SYS_HOST, [listener2.host])
        client.send_message(P.SYS_PORT, [listener2.port])
        time.sleep(0.06)  # let the OSC thread process both commands

        dev.press(3, 5)
        assert _wait_for(lambda: len(listener2.find("/monome/grid/key")) > 0), \
            "key event not received at new destination"
        assert len(listener1.find("/monome/grid/key")) == 0, \
            "key event leaked to old destination"
    finally:
        srv.stop()
        listener1.close()
        listener2.close()
        dev.stop()


# ── /sys/prefix: rewire LED dispatch ────────────────────────────────────

def test_sys_prefix_change_rewires_led_dispatch() -> None:
    """After /sys/prefix, LED commands on the NEW prefix work; old prefix is dead."""
    dev = VirtualGridDevice("pfx-test", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message(P.SYS_PREFIX, ["/mpb"])
        assert _wait_for(lambda: srv.prefix == "/mpb"), "prefix did not update"

        # New prefix should route led/level/set
        client.send_message("/mpb" + P.GRID_LED_LEVEL_SET, [2, 3, 9])
        assert _wait_for(lambda: dev.get_led(2, 3) == 9), \
            "LED command on new prefix was not routed"

        # Old prefix must no longer route
        client.send_message("/monome" + P.GRID_LED_LEVEL_SET, [0, 0, 15])
        time.sleep(0.05)
        assert dev.get_led(0, 0) == 0, "old prefix still routes after change"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_sys_prefix_emits_key_under_new_prefix() -> None:
    """Key events use the NEW prefix after /sys/prefix change."""
    dev = VirtualGridDevice("pfx-key", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message(P.SYS_PREFIX, ["/newpfx"])
        time.sleep(0.06)

        dev.press(0, 0)
        assert _wait_for(lambda: len(listener.find("/newpfx/grid/key")) > 0), \
            "key event not sent on new prefix"
        assert len(listener.find("/monome/grid/key")) == 0, \
            "key event still sent on old prefix"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


# ── /sys/rotation ────────────────────────────────────────────────────────

def test_sys_rotation_updates_device() -> None:
    dev = VirtualGridDevice("rot-test", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message(P.SYS_ROTATION, [180])
        assert _wait_for(lambda: dev.rotation == 180), "rotation did not update"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


# ── /sys/id and /sys/size queries ────────────────────────────────────────

def test_sys_id_query_replies_with_serial() -> None:
    dev = VirtualGridDevice("myserial-42", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message(P.SYS_ID, [])
        assert _wait_for(lambda: len(listener.find(P.SYS_ID)) > 0), \
            "/sys/id reply not received"
        assert listener.find(P.SYS_ID)[0][1][0] == "myserial-42"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_sys_size_query_replies_with_dimensions() -> None:
    dev = VirtualGridDevice("sz-test", 16, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message(P.SYS_SIZE, [])
        assert _wait_for(lambda: len(listener.find(P.SYS_SIZE)) > 0), \
            "/sys/size reply not received"
        assert listener.find(P.SYS_SIZE)[0][1] == [16, 8]
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_sys_info_with_explicit_host_port_target() -> None:
    """Sending /sys/info host port delivers the full sys block to that target."""
    dev = VirtualGridDevice("info-tgt", 8, 8)
    dev.start()
    default_listener = _UDPListener()
    target_listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=default_listener.host,
                          app_port=default_listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message(P.SYS_INFO,
                            [target_listener.host, target_listener.port])
        assert _wait_for(lambda: len(target_listener.received) >= 5), \
            "sys info block not fully received at target"

        addrs = {m[0] for m in target_listener.received}
        for required in (P.SYS_ID, P.SYS_SIZE, P.SYS_HOST,
                         P.SYS_PORT, P.SYS_PREFIX, P.SYS_ROTATION):
            assert required in addrs, f"missing {required} in sys info"

        # Default listener should NOT have received any sys block
        assert len(default_listener.find(P.SYS_ID)) == 0, \
            "sys info leaked to default destination"
    finally:
        srv.stop()
        default_listener.close()
        target_listener.close()
        dev.stop()


# ── Level LED variants ────────────────────────────────────────────────────

def test_led_level_all_sets_uniform_brightness() -> None:
    dev = VirtualGridDevice("lvl-all", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message("/monome" + P.GRID_LED_LEVEL_ALL, [7])
        assert _wait_for(lambda: all(
            dev.get_led(x, y) == 7
            for y in range(8) for x in range(8)
        )), "led/level/all did not set all cells to 7"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_led_level_row_writes_exact_levels() -> None:
    dev = VirtualGridDevice("lvl-row", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        expected = list(range(8))  # [0,1,2,3,4,5,6,7]
        client.send_message("/monome" + P.GRID_LED_LEVEL_ROW, [0, 3, *expected])
        assert _wait_for(lambda: dev.snapshot()[3] == expected), \
            "led/level/row did not write expected levels"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_led_level_col_writes_exact_levels() -> None:
    dev = VirtualGridDevice("lvl-col", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        expected = [i * 2 for i in range(8)]  # [0,2,4,6,8,10,12,14]
        client.send_message("/monome" + P.GRID_LED_LEVEL_COL, [5, 0, *expected])

        def _check() -> bool:
            snap = dev.snapshot()
            return all(snap[y][5] == expected[y] for y in range(8))

        assert _wait_for(_check), "led/level/col did not write expected levels"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_led_level_map_full_quadrant() -> None:
    """64 individual level values routed through level/map."""
    dev = VirtualGridDevice("lvl-map", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        # Checkerboard-ish: value at cell (x,y) = (x + y * 2) % 16
        vals = [(x + y * 2) % 16 for y in range(8) for x in range(8)]
        client.send_message("/monome" + P.GRID_LED_LEVEL_MAP, [0, 0, *vals])

        def _check() -> bool:
            snap = dev.snapshot()
            for y in range(8):
                for x in range(8):
                    if snap[y][x] != (x + y * 2) % 16:
                        return False
            return True

        assert _wait_for(_check), "led/level/map did not write expected pattern"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


# ── Binary mask LED variants ──────────────────────────────────────────────

def test_led_row_binary_mask() -> None:
    """Binary /grid/led/row uses 8-bit mask, expanding to 0/15 per column."""
    dev = VirtualGridDevice("bin-row", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        mask = 0b10101010
        client.send_message("/monome" + P.GRID_LED_ROW, [0, 4, mask])

        def _check() -> bool:
            row = dev.snapshot()[4]
            return all(row[x] == (15 if (mask >> x) & 1 else 0) for x in range(8))

        assert _wait_for(_check), "led/row mask did not expand to expected levels"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_led_col_binary_mask() -> None:
    """Binary /grid/led/col uses 8-bit mask, expanding to 0/15 per row."""
    dev = VirtualGridDevice("bin-col", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        mask = 0b11001100
        client.send_message("/monome" + P.GRID_LED_COL, [2, 0, mask])

        def _check() -> bool:
            snap = dev.snapshot()
            return all(snap[y][2] == (15 if (mask >> y) & 1 else 0) for y in range(8))

        assert _wait_for(_check), "led/col mask did not expand to expected levels"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_led_intensity_command_does_not_crash() -> None:
    """/grid/led/intensity is accepted and forwarded to device without error."""
    dev = VirtualGridDevice("int-test", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message("/monome" + P.GRID_LED_INTENSITY, [10])
        time.sleep(0.05)  # just verify no crash or stuck state
        # Virtual device stores intensity silently; LED state is unaffected
        assert all(dev.get_led(x, y) == 0 for y in range(8) for x in range(8))
    finally:
        srv.stop()
        listener.close()
        dev.stop()


# ── Tilt ──────────────────────────────────────────────────────────────────

def test_tilt_event_forwarded_as_osc() -> None:
    """A synthetic tilt on the device is forwarded over OSC to the app port."""
    dev = VirtualGridDevice("tilt-fwd", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        # The OSC server has registered _on_device_tilt as the primary tilt cb.
        dev._fire_tilt(0, 100, 50, 200)
        expected_addr = "/monome" + P.TILT
        assert _wait_for(lambda: len(listener.find(expected_addr)) > 0), \
            "tilt event was not forwarded over OSC"
        msg = listener.find(expected_addr)[0]
        assert msg[1] == [0, 100, 50, 200], \
            f"tilt params mismatch: {msg[1]}"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_tilt_set_command_accepted_without_crash() -> None:
    """/tilt/set is silently accepted by a virtual device (tilt_set is no-op)."""
    dev = VirtualGridDevice("tilt-set", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        client = udp_client.SimpleUDPClient("127.0.0.1", srv.listen_port)
        client.send_message("/monome" + P.TILT_SET, [0, 1])
        time.sleep(0.05)
        # Verify server is still operational after the command
        client.send_message(P.SYS_ID, [])
        assert _wait_for(lambda: len(listener.find(P.SYS_ID)) > 0), \
            "server became unresponsive after /tilt/set"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


def test_multiple_tilt_events_all_forwarded() -> None:
    """All synthetic tilt events in a burst reach the app listener."""
    dev = VirtualGridDevice("tilt-burst", 8, 8)
    dev.start()
    listener = _UDPListener()
    srv = DeviceOscServer(dev, prefix="/monome",
                          host=listener.host, app_port=listener.port)
    srv.start()
    try:
        tilt_addr = "/monome" + P.TILT
        for n_val in range(5):
            dev._fire_tilt(0, n_val * 50, n_val * 30, 128)
        assert _wait_for(lambda: len(listener.find(tilt_addr)) >= 5), \
            "not all tilt events were forwarded"
    finally:
        srv.stop()
        listener.close()
        dev.stop()


# ── serialosc discovery ────────────────────────────────────────────────────

def test_discovery_list_response_contains_device() -> None:
    """DiscoveryServer replies to /serialosc/list with /serialosc/device entries."""
    from monomepybridge.serialosc.discovery_server import (
        AdvertisedDevice,
        DiscoveryServer,
    )

    advertised = [
        AdvertisedDevice(id="virt-0001", type_name="virtual 8x8", port=9000),
        AdvertisedDevice(id="virt-0002", type_name="virtual 16x8", port=9001),
    ]
    disc = DiscoveryServer(device_provider=lambda: advertised, port=0)
    disc.start()
    try:
        reply_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        reply_sock.bind(("127.0.0.1", 0))
        reply_sock.settimeout(1.0)
        rhost, rport = reply_sock.getsockname()

        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            msg = build_osc_message(P.SERIALOSC_LIST, [rhost, rport])
            send_sock.sendto(msg, ("127.0.0.1", disc.port))

            received: list[tuple[str, list]] = []
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                try:
                    data, _ = reply_sock.recvfrom(65535)
                    pkt = OscPacket(data)
                    for tm in pkt.messages:
                        received.append((tm.message.address,
                                         list(tm.message.params)))
                except socket.timeout:
                    break
        finally:
            send_sock.close()
            reply_sock.close()

        device_msgs = [m for m in received if m[0] == P.SERIALOSC_DEVICE]
        assert len(device_msgs) == 2, \
            f"expected 2 device entries, got {len(device_msgs)}"
        ids = [m[1][0] for m in device_msgs]
        assert "virt-0001" in ids
        assert "virt-0002" in ids
        ports = [m[1][2] for m in device_msgs]
        assert 9000 in ports
        assert 9001 in ports
    finally:
        disc.stop()


def test_discovery_notify_then_broadcast_add() -> None:
    """A client that sends /serialosc/notify receives /serialosc/add on next add."""
    from monomepybridge.serialosc.discovery_server import DiscoveryServer

    disc = DiscoveryServer(device_provider=lambda: [], port=0)
    disc.start()
    try:
        reply_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        reply_sock.bind(("127.0.0.1", 0))
        reply_sock.settimeout(1.0)
        rhost, rport = reply_sock.getsockname()

        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Subscribe
            msg = build_osc_message(P.SERIALOSC_NOTIFY, [rhost, rport])
            send_sock.sendto(msg, ("127.0.0.1", disc.port))
            time.sleep(0.05)

            # Trigger an add notification
            disc.broadcast_add("virt-notify-test")

            received: list[tuple[str, list]] = []
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                try:
                    data, _ = reply_sock.recvfrom(65535)
                    pkt = OscPacket(data)
                    for tm in pkt.messages:
                        received.append((tm.message.address,
                                         list(tm.message.params)))
                except socket.timeout:
                    break
        finally:
            send_sock.close()
            reply_sock.close()

        add_msgs = [m for m in received if m[0] == P.SERIALOSC_ADD]
        assert len(add_msgs) == 1, \
            f"expected 1 /serialosc/add, got {len(add_msgs)}"
        assert add_msgs[0][1][0] == "virt-notify-test"
    finally:
        disc.stop()
