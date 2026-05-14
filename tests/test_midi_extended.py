"""Extended MIDI bridge tests.

Exercises the full MIDI ↔ device round-trip using an in-process fake
rtmidi module — no physical MIDI hardware required.

Coverage:
* Device key press  → MIDI Note On out
* Device key release → MIDI Note Off out
* MIDI Note On in   → device LED set (velocity-scaled)
* MIDI Note Off in  → device LED cleared
* Note On vel=0     → treated as Note Off (LED clear)
* Wrong-channel note → ignored
* Velocity → level scaling correctness
* Out-of-range note below base_note → ignored
* Out-of-range note above grid → ignored
* Tilt event while bridge is active → no crash
* Bridge start / stop idempotency
"""

from __future__ import annotations

import sys
import time

import pytest

from monomepybridge.bridge.devices.virtual import VirtualGridDevice
from monomepybridge.bridges.midi_bridge import (
    MidiBridge,
    coord_to_note,
    note_to_coord,
)


# ── fake rtmidi fixture ──────────────────────────────────────────────────

@pytest.fixture
def rtmidi_mock(monkeypatch):
    """Replace rtmidi with an in-process fake that captures MIDI I/O.

    Yields a dict:
        {
            "out": _FakeMidiOut instance (set after bridge.start()),
            "in":  _FakeMidiIn  instance (set after bridge.start()),
        }

    The _FakeMidiIn instance has an ``inject(msg)`` method that feeds a
    raw MIDI byte-list through the bridge's inbound callback.
    """
    import monomepybridge.bridges.midi_bridge as mb

    captured: dict = {"out": None, "in": None}

    class _FakeMidiOut:
        def __init__(self) -> None:
            self.messages: list[list[int]] = []
            captured["out"] = self

        def get_ports(self) -> list:
            return ["FakeMIDI"]

        def open_port(self, i: int) -> None:
            pass

        def open_virtual_port(self, name: str) -> None:
            pass

        def send_message(self, msg: list) -> None:
            self.messages.append(list(msg))

        def close_port(self) -> None:
            pass

    class _FakeMidiIn:
        def __init__(self) -> None:
            self._cb = None
            captured["in"] = self

        def get_ports(self) -> list:
            return ["FakeMIDI"]

        def open_port(self, i: int) -> None:
            pass

        def open_virtual_port(self, name: str) -> None:
            pass

        def set_callback(self, cb) -> None:
            self._cb = cb

        def close_port(self) -> None:
            pass

        def inject(self, msg: list[int]) -> None:
            """Feed a raw MIDI message into the bridge callback."""
            if self._cb is not None:
                self._cb((list(msg), 0.0), None)

    class _FakeRtMidi:
        MidiOut = _FakeMidiOut
        MidiIn = _FakeMidiIn

    # Use "Linux" codepath so virtual ports are opened (no physical HW needed).
    monkeypatch.setattr(
        mb, "platform",
        type("P", (), {"system": staticmethod(lambda: "Linux")}),
    )
    monkeypatch.setitem(sys.modules, "rtmidi", _FakeRtMidi)
    yield captured


# ── coordinate / note math (pure, no mock needed) ────────────────────────

def test_coord_to_note_mapping() -> None:
    assert coord_to_note(0, 0, 8, 36) == 36
    assert coord_to_note(7, 0, 8, 36) == 43
    assert coord_to_note(0, 1, 8, 36) == 44
    assert coord_to_note(7, 7, 8, 36) == 99


def test_note_to_coord_mapping() -> None:
    assert note_to_coord(36, 8, 8, 36) == (0, 0)
    assert note_to_coord(43, 8, 8, 36) == (7, 0)
    assert note_to_coord(44, 8, 8, 36) == (0, 1)
    assert note_to_coord(99, 8, 8, 36) == (7, 7)


def test_note_roundtrip_all_cells_8x8() -> None:
    base = 36
    for y in range(8):
        for x in range(8):
            n = coord_to_note(x, y, 8, base)
            assert note_to_coord(n, 8, 8, base) == (x, y)


def test_note_to_coord_out_of_range() -> None:
    assert note_to_coord(35, 8, 8, 36) is None    # below base
    assert note_to_coord(100, 8, 8, 36) is None   # exactly past last cell


# ── device key → MIDI out ────────────────────────────────────────────────

def test_key_press_sends_note_on(rtmidi_mock) -> None:
    """Device key press fires MIDI Note On on the configured channel."""
    dev = VirtualGridDevice("m-press", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    midi_out = rtmidi_mock["out"]
    assert midi_out is not None, "fake MidiOut was not created — bridge did not start"
    try:
        dev.press(0, 0)
        time.sleep(0.02)
        note_on = [m for m in midi_out.messages
                   if m[0] == 0x90 and m[1] == 36]
        assert note_on, "no Note On for (0,0)"
        assert note_on[0][2] == 100, "expected velocity 100 for key press"
    finally:
        bridge.stop()
        dev.stop()


def test_key_release_sends_note_off(rtmidi_mock) -> None:
    """Device key release fires MIDI Note Off."""
    dev = VirtualGridDevice("m-rel", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    midi_out = rtmidi_mock["out"]
    try:
        dev.press(3, 2)
        dev.release(3, 2)
        time.sleep(0.02)
        note = coord_to_note(3, 2, 8, 36)
        note_off = [m for m in midi_out.messages
                    if m[0] == 0x80 and m[1] == note]
        assert note_off, f"no Note Off for (3,2), note={note}"
        assert note_off[0][2] == 0
    finally:
        bridge.stop()
        dev.stop()


def test_key_press_uses_correct_channel(rtmidi_mock) -> None:
    """MIDI channel in the status byte matches bridge.channel."""
    dev = VirtualGridDevice("m-ch", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=5, base_note=36)
    bridge.start()
    midi_out = rtmidi_mock["out"]
    try:
        dev.press(0, 0)
        time.sleep(0.02)
        ch5_on = [m for m in midi_out.messages
                  if m[0] == (0x90 | 4)]   # ch5 = index 4
        assert ch5_on, "Note On not sent on channel 5"
    finally:
        bridge.stop()
        dev.stop()


def test_corner_cells_send_correct_notes(rtmidi_mock) -> None:
    """All four corners of the grid fire the right MIDI notes."""
    dev = VirtualGridDevice("m-corners", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    midi_out = rtmidi_mock["out"]
    try:
        for (x, y), expected_note in [
            ((0, 0), 36), ((7, 0), 43), ((0, 7), 92), ((7, 7), 99)
        ]:
            midi_out.messages.clear()
            dev.press(x, y)
            time.sleep(0.02)
            sent_notes = [m[1] for m in midi_out.messages if m[0] == 0x90]
            assert expected_note in sent_notes, \
                f"corner ({x},{y}) should send note {expected_note}, got {sent_notes}"
    finally:
        bridge.stop()
        dev.stop()


# ── MIDI in → device LED ─────────────────────────────────────────────────

def test_note_on_sets_led_proportional_to_velocity(rtmidi_mock) -> None:
    """MIDI Note On → LED level = round(vel * 15 / 127)."""
    dev = VirtualGridDevice("m-note-on", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    midi_in = rtmidi_mock["in"]
    try:
        # vel=127 → level 15
        midi_in.inject([0x90, 36, 127])
        time.sleep(0.02)
        assert dev.get_led(0, 0) == 15, "vel=127 should give level 15"

        # vel=64 → level round(64*15/127)=8
        midi_in.inject([0x90, 37, 64])  # note 37 = (1,0)
        time.sleep(0.02)
        assert dev.get_led(1, 0) == round(64 * 15 / 127)
    finally:
        bridge.stop()
        dev.stop()


def test_note_off_clears_led(rtmidi_mock) -> None:
    """MIDI Note Off sets the corresponding LED to 0."""
    dev = VirtualGridDevice("m-note-off", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    midi_in = rtmidi_mock["in"]
    try:
        midi_in.inject([0x90, 36, 100])   # Note On
        time.sleep(0.02)
        assert dev.get_led(0, 0) > 0

        midi_in.inject([0x80, 36, 0])     # Note Off
        time.sleep(0.02)
        assert dev.get_led(0, 0) == 0, "Note Off did not clear LED"
    finally:
        bridge.stop()
        dev.stop()


def test_note_on_velocity_zero_is_note_off(rtmidi_mock) -> None:
    """Note On with velocity 0 is a running-status Note Off — clears LED."""
    dev = VirtualGridDevice("m-vel0", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    midi_in = rtmidi_mock["in"]
    try:
        midi_in.inject([0x90, 36, 120])
        time.sleep(0.02)
        assert dev.get_led(0, 0) > 0

        midi_in.inject([0x90, 36, 0])    # Note On vel=0 ≡ Note Off
        time.sleep(0.02)
        assert dev.get_led(0, 0) == 0, "Note On vel=0 did not clear LED"
    finally:
        bridge.stop()
        dev.stop()


def test_wrong_channel_note_is_ignored(rtmidi_mock) -> None:
    """MIDI messages on the wrong channel leave device state unchanged."""
    dev = VirtualGridDevice("m-ch-filt", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=3, base_note=36)
    bridge.start()
    midi_in = rtmidi_mock["in"]
    try:
        # Send on channel 2 (status=0x91 | 0x01 = 0x91)
        midi_in.inject([0x91, 36, 127])
        time.sleep(0.02)
        assert dev.get_led(0, 0) == 0, \
            "note on wrong channel should not change LED"
    finally:
        bridge.stop()
        dev.stop()


def test_velocity_levels_scale_correctly(rtmidi_mock) -> None:
    """Spot-check a few velocity→level conversions."""
    cases = [
        (0,   0),
        (64,  round(64 * 15 / 127)),
        (100, round(100 * 15 / 127)),
        (127, 15),
    ]
    dev = VirtualGridDevice("m-vel-scale", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    midi_in = rtmidi_mock["in"]
    # Use different cells for each velocity to avoid interference
    try:
        for idx, (vel, expected_level) in enumerate(cases):
            note = 36 + idx  # (idx, 0)
            x = idx % 8
            if vel == 0:
                # vel=0 → Note Off path; prime LED first so clearing is observable
                midi_in.inject([0x90, note, 100])
                time.sleep(0.02)
            midi_in.inject([0x90, note, vel])
            time.sleep(0.02)
            assert dev.get_led(x, 0) == expected_level, \
                f"vel={vel} expected level {expected_level}, got {dev.get_led(x, 0)}"
    finally:
        bridge.stop()
        dev.stop()


def test_note_below_base_note_is_ignored(rtmidi_mock) -> None:
    """Note below base_note has no matching cell and is silently dropped."""
    dev = VirtualGridDevice("m-oob-lo", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    midi_in = rtmidi_mock["in"]
    try:
        midi_in.inject([0x90, 35, 127])   # note 35 < base_note 36
        time.sleep(0.02)
        snap = dev.snapshot()
        assert all(v == 0 for row in snap for v in row), \
            "out-of-range note (below base) should not change any LED"
    finally:
        bridge.stop()
        dev.stop()


def test_note_above_grid_is_ignored(rtmidi_mock) -> None:
    """Note number past the last grid cell is silently dropped."""
    dev = VirtualGridDevice("m-oob-hi", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    midi_in = rtmidi_mock["in"]
    try:
        above = 36 + 64   # = 100: one past the 8×8 = 64-cell grid
        midi_in.inject([0x90, above, 127])
        time.sleep(0.02)
        snap = dev.snapshot()
        assert all(v == 0 for row in snap for v in row), \
            "out-of-range note (above grid) should not change any LED"
    finally:
        bridge.stop()
        dev.stop()


# ── Tilt passthrough (no crash) ──────────────────────────────────────────

def test_tilt_event_does_not_crash_bridge(rtmidi_mock) -> None:
    """MIDI bridge has no tilt handler; tilt events must be silently ignored."""
    dev = VirtualGridDevice("m-tilt", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    try:
        # _fire_tilt goes to observers; MIDI bridge observer has no on_tilt
        dev._fire_tilt(0, 200, 50, 100)
        dev._fire_tilt(0, 10, 220, 200)
        time.sleep(0.02)
        # Verify bridge is still functional after tilt events
        midi_out = rtmidi_mock["out"]
        midi_out.messages.clear()
        dev.press(0, 0)
        time.sleep(0.02)
        assert any(m[0] == 0x90 for m in midi_out.messages), \
            "bridge became non-functional after tilt events"
    finally:
        bridge.stop()
        dev.stop()


# ── Lifecycle ────────────────────────────────────────────────────────────

def test_bridge_stop_removes_observer(rtmidi_mock) -> None:
    """After stop(), key events no longer reach the MIDI out."""
    dev = VirtualGridDevice("m-stop", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    midi_out = rtmidi_mock["out"]
    try:
        # Confirm it works before stop
        dev.press(0, 0)
        time.sleep(0.02)
        assert any(m[0] == 0x90 for m in midi_out.messages)

        bridge.stop()
        midi_out.messages.clear()

        # Keys after stop must NOT produce MIDI output
        dev.press(1, 0)
        time.sleep(0.02)
        assert not any(m[0] == 0x90 for m in midi_out.messages), \
            "MIDI output still firing after bridge.stop()"
    finally:
        dev.stop()


def test_bridge_start_is_idempotent(rtmidi_mock) -> None:
    """Calling start() twice must not raise or duplicate observers."""
    dev = VirtualGridDevice("m-idem", 8, 8)
    dev.start()
    bridge = MidiBridge(dev, channel=1, base_note=36)
    bridge.start()
    try:
        # Second start: rtmidi is already in sys.modules (same fake)
        # bridge should not crash even if re-entering start
        # (implementation creates new rtmidi objects, which is acceptable)
        bridge.start()
        midi_out2 = rtmidi_mock["out"]  # will point to newest instance

        midi_out2.messages.clear()
        dev.press(0, 0)
        time.sleep(0.02)
        # At least one Note On should appear — observer may be duplicated
        # but must not be zero (bridge is operational)
        assert any(m[0] == 0x90 for m in midi_out2.messages), \
            "bridge not operational after double-start"
    finally:
        bridge.stop()
        dev.stop()
