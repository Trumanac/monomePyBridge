"""serialosc / monome OSC address constants + payload helpers.

Reference: https://monome.org/docs/osc/

Addresses are organised by namespace:

* ``/serialosc/...``         — discovery (the daemon talks to *clients* on UDP 12002)
* ``/sys/...``               — per-device system messages
* ``<prefix>/grid/...``      — per-device grid LED + key messages
* ``<prefix>/tilt[/set]``    — per-device tilt streaming
"""

from __future__ import annotations

# ── discovery ───────────────────────────────────────────────────────────
SERIALOSC_LIST   = "/serialosc/list"
SERIALOSC_NOTIFY = "/serialosc/notify"
SERIALOSC_DEVICE = "/serialosc/device"
SERIALOSC_ADD    = "/serialosc/add"
SERIALOSC_REMOVE = "/serialosc/remove"

DEFAULT_SERIALOSC_PORT = 12002

# ── /sys/ ───────────────────────────────────────────────────────────────
SYS_PORT     = "/sys/port"
SYS_HOST     = "/sys/host"
SYS_ID       = "/sys/id"
SYS_PREFIX   = "/sys/prefix"
SYS_ROTATION = "/sys/rotation"
SYS_SIZE     = "/sys/size"
SYS_INFO     = "/sys/info"
SYS_CONNECT  = "/sys/connect"
SYS_DISCONNECT = "/sys/disconnect"

# ── per-prefix grid (suffixes; prepend "<prefix>") ──────────────────────
GRID_KEY              = "/grid/key"
GRID_LED_SET          = "/grid/led/set"
GRID_LED_ALL          = "/grid/led/all"
GRID_LED_MAP          = "/grid/led/map"
GRID_LED_ROW          = "/grid/led/row"
GRID_LED_COL          = "/grid/led/col"
GRID_LED_INTENSITY    = "/grid/led/intensity"
GRID_LED_LEVEL_SET    = "/grid/led/level/set"
GRID_LED_LEVEL_ALL    = "/grid/led/level/all"
GRID_LED_LEVEL_MAP    = "/grid/led/level/map"
GRID_LED_LEVEL_ROW    = "/grid/led/level/row"
GRID_LED_LEVEL_COL    = "/grid/led/level/col"

TILT       = "/tilt"
TILT_SET   = "/tilt/set"


# ── helpers ─────────────────────────────────────────────────────────────

def normalize_prefix(prefix: str) -> str:
    """Return a prefix that always starts with '/' and never trails one."""
    p = (prefix or "").strip()
    if not p:
        return "/monome"
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p


def expand_row_mask(mask: int) -> list[int]:
    """Convert an 8-bit serialosc row mask to 8 binary brightness values.

    serialosc/monomeserial pack an LED row as a single int where bit 0 =
    column 0 and bit 7 = column 7. We expand to a list of 0/15 levels so
    the rest of the bridge speaks one normalised brightness model.
    """
    return [15 if (mask >> i) & 1 else 0 for i in range(8)]


def pack_row_mask(levels: list[int]) -> int:
    """Inverse of :func:`expand_row_mask`. Levels >= 1 light the bit."""
    out = 0
    for i, lvl in enumerate(levels[:8]):
        if lvl >= 1:
            out |= 1 << i
    return out
