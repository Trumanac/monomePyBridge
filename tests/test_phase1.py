"""Phase 1 tests — device abstraction, virtual driver, discovery classifier."""

from __future__ import annotations

from types import SimpleNamespace


from monomepybridge.bridge import DeviceProtocol, build_device
from monomepybridge.bridge.devices.virtual import VirtualGridDevice
from monomepybridge.discovery import GuessedProtocol, MatchTier
from monomepybridge.discovery.scanner import _classify, _to_discovered  # type: ignore


# ── Virtual device ──────────────────────────────────────────────────────

def test_virtual_grid_basic_led_state():
    dev = VirtualGridDevice(width=8, height=8)
    dev.start()
    try:
        assert dev.width == 8 and dev.height == 8
        assert dev.info.protocol == DeviceProtocol.PROTO_VIRTUAL
        dev.led_set(3, 4, 12)
        assert dev.get_led(3, 4) == 12
        dev.led_all(0)
        assert dev.snapshot() == [[0] * 8 for _ in range(8)]
        dev.led_row(0, 2, [15] * 8)
        assert dev.snapshot()[2] == [15] * 8
        dev.led_col(7, 0, [5] * 8)
        for y in range(8):
            assert dev.snapshot()[y][7] == 5
    finally:
        dev.stop()


def test_virtual_grid_clamps_levels():
    dev = VirtualGridDevice()
    dev.start()
    try:
        dev.led_set(0, 0, 99)
        dev.led_set(1, 0, -5)
        assert dev.get_led(0, 0) == 15
        assert dev.get_led(1, 0) == 0
    finally:
        dev.stop()


def test_virtual_grid_callbacks_fire():
    from monomepybridge.bridge import DeviceCallbacks
    events = []
    dev = VirtualGridDevice()
    dev.set_callbacks(DeviceCallbacks(on_key=lambda x, y, s: events.append((x, y, s))))
    dev.start()
    try:
        dev.press(2, 3)
        dev.release(2, 3)
        assert events == [(2, 3, 1), (2, 3, 0)]
    finally:
        dev.stop()


def test_led_map_default_calls_rows():
    dev = VirtualGridDevice()
    dev.start()
    try:
        dev.led_map(0, 0, [[i for i in range(8)] for _ in range(8)])
        snap = dev.snapshot()
        for y in range(8):
            assert snap[y] == list(range(8))
    finally:
        dev.stop()


# ── Discovery classifier ────────────────────────────────────────────────

def _fake_port(**kw):
    """Build a duck-typed object resembling pyserial's ListPortInfo."""
    defaults = dict(
        device="COM7",
        description="",
        manufacturer="",
        product="",
        serial_number="",
        vid=None,
        pid=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_classify_monome_string():
    p = _fake_port(description="monome 40h kit", manufacturer="monome", vid=0x0403, pid=0x6001)
    tier, proto = _classify(p)
    assert tier == MatchTier.MATCH_MONOME
    assert proto == GuessedProtocol.PROTO_40H


def test_classify_bare_ftdi_guesses_40h():
    p = _fake_port(description="USB Serial Port", vid=0x0403, pid=0x6001)
    tier, proto = _classify(p)
    assert tier == MatchTier.MATCH_FTDI
    assert proto == GuessedProtocol.PROTO_40H


def test_classify_unknown_passes_through():
    p = _fake_port(description="Generic UART", vid=0x10C4, pid=0xEA60)
    tier, proto = _classify(p)
    assert tier == MatchTier.MATCH_UNKNOWN
    assert proto == GuessedProtocol.PROTO_UNKNOWN


def test_classify_mext_serial():
    p = _fake_port(description="monome 128 mext", serial_number="m1000123", vid=0x0403, pid=0x6015)
    tier, proto = _classify(p)
    assert tier == MatchTier.MATCH_MONOME
    assert proto == GuessedProtocol.PROTO_MEXT


def test_to_discovered_preserves_fields():
    p = _fake_port(
        device="/dev/ttyUSB0",
        description="monome",
        manufacturer="monome",
        product="m64-0858",
        serial_number="m64-0858",
        vid=0x0403,
        pid=0x6001,
    )
    dp = _to_discovered(p)
    assert dp.device == "/dev/ttyUSB0"
    assert dp.serial_number == "m64-0858"
    assert dp.is_monome_hit
    assert dp.guessed_protocol == GuessedProtocol.PROTO_40H
    assert dp.stable_id == "m64-0858"


# ── Scanner diff logic ──────────────────────────────────────────────────

def test_scanner_emits_add_remove(monkeypatch):
    from monomepybridge.discovery.scanner import DeviceScanner, DiscoveredPort, MatchTier, GuessedProtocol

    added: list[DiscoveredPort] = []
    removed: list[DiscoveredPort] = []

    fake_ports = [
        DiscoveredPort(
            device="COM7", serial_number="m64-0858",
            tier=MatchTier.MATCH_MONOME, guessed_protocol=GuessedProtocol.PROTO_40H,
        )
    ]

    monkeypatch.setattr(
        "monomepybridge.discovery.scanner.list_serial_ports",
        lambda include_unknown=False: list(fake_ports),
    )

    scn = DeviceScanner(poll_interval=10.0)
    scn.set_callbacks(on_added=added.append, on_removed=removed.append)
    scn.scan_once()
    assert len(added) == 1 and added[0].serial_number == "m64-0858"
    assert removed == []

    # No change.
    scn.scan_once()
    assert len(added) == 1
    assert removed == []

    # Device disappears.
    fake_ports.clear()
    scn.scan_once()
    assert len(removed) == 1


# ── Factory ─────────────────────────────────────────────────────────────

def test_factory_returns_none_for_unknown():
    from monomepybridge.discovery.scanner import DiscoveredPort

    dp = DiscoveredPort(device="COM3", tier=MatchTier.MATCH_UNKNOWN,
                        guessed_protocol=GuessedProtocol.PROTO_UNKNOWN)
    assert build_device(dp) is None


def test_factory_returns_none_for_unimplemented_protocols():
    from monomepybridge.discovery.scanner import DiscoveredPort
    for proto in (GuessedProtocol.PROTO_SERIES, GuessedProtocol.PROTO_MEXT):
        dp = DiscoveredPort(device="COM3", tier=MatchTier.MATCH_MONOME,
                            guessed_protocol=proto)
        assert build_device(dp) is None
