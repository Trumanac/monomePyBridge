"""Per-device serialosc-style OSC server.

One :class:`DeviceOscServer` is created per attached :class:`Device`. It:

* Owns a UDP socket on an auto-allocated port (the "device port" in
  serialosc terms).
* Receives ``/sys/...`` and ``<prefix>/grid/led/...`` from client apps and
  forwards LED state changes to the underlying :class:`Device`.
* Forwards key + tilt events from the device back out to the configured
  destination ``host:port``.

Address dispatch follows the canonical monome OSC spec; both binary
(``/grid/led/set``) and 0-15 level (``/grid/led/level/set``) variants are
supported. Devices that don't support brightness levels (e.g. 40h)
threshold internally inside the driver — this layer doesn't need to know.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..bridge import Device
from ..osc import protocol as P
from ..osc.endpoint import OscEndpoint

log = logging.getLogger("monomepybridge")


class DeviceOscServer:
    """OSC bridge for a single :class:`Device`."""

    def __init__(
        self,
        device: Device,
        prefix: str = "/monome",
        host: str = "127.0.0.1",
        app_port: int = 8000,
        listen_host: str = "0.0.0.0",
        listen_port: int = 0,
    ) -> None:
        self.device = device
        self.prefix = P.normalize_prefix(prefix)
        self.host = host
        self.app_port = int(app_port)

        self._endpoint = OscEndpoint(host=listen_host, port=listen_port)
        self._wire_device_callbacks()
        self._register_handlers()

    # ── lifecycle ────────────────────────────────────────────────────────
    @property
    def listen_port(self) -> int:
        return self._endpoint.port

    @property
    def listen_host(self) -> str:
        return self._endpoint.host

    def start(self) -> None:
        self._endpoint.start(name=f"mpb-osc-{self.device.id}")
        log.info(
            "device server: %s prefix=%s listen=%d -> %s:%d",
            self.device.id, self.prefix, self.listen_port, self.host, self.app_port,
        )

    def stop(self) -> None:
        self._endpoint.stop()

    # ── wiring ───────────────────────────────────────────────────────────
    def _wire_device_callbacks(self) -> None:
        from ..bridge import DeviceCallbacks
        self.device.set_callbacks(
            DeviceCallbacks(
                on_key=self._on_device_key,
                on_tilt=self._on_device_tilt,
            )
        )

    def _register_handlers(self) -> None:
        ep = self._endpoint

        # ── /sys handlers ────────────────────────────────────────────────
        ep.register(P.SYS_PORT, self._h_sys_port)
        ep.register(P.SYS_HOST, self._h_sys_host)
        ep.register(P.SYS_PREFIX, self._h_sys_prefix)
        ep.register(P.SYS_ROTATION, self._h_sys_rotation)
        ep.register(P.SYS_INFO, self._h_sys_info)
        ep.register(P.SYS_ID, self._h_sys_id_query)
        ep.register(P.SYS_SIZE, self._h_sys_size_query)

        # ── prefix-scoped handlers ───────────────────────────────────────
        # We register a single prefix wildcard handler and dispatch on
        # the suffix internally so the prefix can change at runtime
        # without re-registering every leaf.
        ep.register_prefix(self.prefix, self._h_prefix_dispatch)

    # ── /sys handlers ────────────────────────────────────────────────────
    def _h_sys_port(self, addr: str, args: list, src: tuple[str, int]) -> None:
        if args and isinstance(args[0], int):
            self.app_port = int(args[0])
            log.info("[%s] /sys/port -> %d", self.device.id, self.app_port)

    def _h_sys_host(self, addr: str, args: list, src: tuple[str, int]) -> None:
        if args and isinstance(args[0], str):
            self.host = args[0]
            log.info("[%s] /sys/host -> %s", self.device.id, self.host)

    def _h_sys_prefix(self, addr: str, args: list, src: tuple[str, int]) -> None:
        if args and isinstance(args[0], str):
            old = self.prefix
            self.prefix = P.normalize_prefix(args[0])
            self._endpoint.unregister_prefix(old)
            self._endpoint.register_prefix(self.prefix, self._h_prefix_dispatch)
            log.info("[%s] /sys/prefix %s -> %s", self.device.id, old, self.prefix)

    def _h_sys_rotation(self, addr: str, args: list, src: tuple[str, int]) -> None:
        if args and isinstance(args[0], int):
            deg = int(args[0])
            self.device.set_rotation(deg)
            log.info("[%s] /sys/rotation -> %d", self.device.id, deg)

    def _h_sys_info(self, addr: str, args: list, src: tuple[str, int]) -> None:
        # /sys/info  OR  /sys/info <host:str> <port:int>
        if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], int):
            target = (args[0], int(args[1]))
        elif len(args) == 1 and isinstance(args[0], int):
            target = (self.host, int(args[0]))
        else:
            target = (self.host, self.app_port)
        self._send_sys_block(*target)

    def _h_sys_id_query(self, addr: str, args: list, src: tuple[str, int]) -> None:
        self._endpoint.send(self.host, self.app_port, P.SYS_ID, self.device.id)

    def _h_sys_size_query(self, addr: str, args: list, src: tuple[str, int]) -> None:
        self._endpoint.send(self.host, self.app_port, P.SYS_SIZE,
                            self.device.width, self.device.height)

    def _send_sys_block(self, host: str, port: int) -> None:
        ep = self._endpoint
        ep.send(host, port, P.SYS_ID, self.device.id)
        ep.send(host, port, P.SYS_SIZE, self.device.width, self.device.height)
        ep.send(host, port, P.SYS_HOST, self.host)
        ep.send(host, port, P.SYS_PORT, self.app_port)
        ep.send(host, port, P.SYS_PREFIX, self.prefix)
        ep.send(host, port, P.SYS_ROTATION, int(self.device.rotation))

    # ── prefix dispatch ──────────────────────────────────────────────────
    def _h_prefix_dispatch(self, addr: str, args: list, src: tuple[str, int]) -> None:
        if not addr.startswith(self.prefix):
            return
        suffix = addr[len(self.prefix):]
        try:
            if suffix == P.GRID_LED_SET:
                self._h_led_set(args)
            elif suffix == P.GRID_LED_ALL:
                self._h_led_all(args)
            elif suffix == P.GRID_LED_MAP:
                self._h_led_map(args)
            elif suffix == P.GRID_LED_ROW:
                self._h_led_row(args)
            elif suffix == P.GRID_LED_COL:
                self._h_led_col(args)
            elif suffix == P.GRID_LED_INTENSITY:
                self._h_led_intensity(args)
            elif suffix == P.GRID_LED_LEVEL_SET:
                self._h_level_set(args)
            elif suffix == P.GRID_LED_LEVEL_ALL:
                self._h_level_all(args)
            elif suffix == P.GRID_LED_LEVEL_MAP:
                self._h_level_map(args)
            elif suffix == P.GRID_LED_LEVEL_ROW:
                self._h_level_row(args)
            elif suffix == P.GRID_LED_LEVEL_COL:
                self._h_level_col(args)
            elif suffix == P.TILT_SET:
                self._h_tilt_set(args)
            else:
                log.debug("[%s] unhandled %s", self.device.id, addr)
        except Exception:
            log.exception("[%s] handler error for %s", self.device.id, addr)

    # ── binary LED handlers (s = 0|1) ────────────────────────────────────
    def _h_led_set(self, args: list) -> None:
        if len(args) >= 3:
            x, y, s = int(args[0]), int(args[1]), int(args[2])
            self.device.led_set(x, y, 15 if s else 0)

    def _h_led_all(self, args: list) -> None:
        if args:
            self.device.led_all(15 if int(args[0]) else 0)

    def _h_led_map(self, args: list) -> None:
        # /grid/led/map x_off y_off m0 m1 m2 m3 m4 m5 m6 m7
        if len(args) >= 10:
            x_off, y_off = int(args[0]), int(args[1])
            for i in range(8):
                mask = int(args[2 + i])
                levels = P.expand_row_mask(mask)
                self.device.led_row(x_off, y_off + i, levels)

    def _h_led_row(self, args: list) -> None:
        # /grid/led/row x_off y mask [mask...]
        if len(args) >= 3:
            x_off, y = int(args[0]), int(args[1])
            for i, mask in enumerate(args[2:]):
                self.device.led_row(x_off + i * 8, y, P.expand_row_mask(int(mask)))

    def _h_led_col(self, args: list) -> None:
        # /grid/led/col x y_off mask [mask...]
        if len(args) >= 3:
            x, y_off = int(args[0]), int(args[1])
            for i, mask in enumerate(args[2:]):
                # Column mask: bit n -> y_off + i*8 + n
                col_levels: list[int] = []
                m = int(mask)
                for n in range(8):
                    col_levels.append(15 if (m >> n) & 1 else 0)
                self.device.led_col(x, y_off + i * 8, col_levels)

    def _h_led_intensity(self, args: list) -> None:
        if args:
            self.device.set_intensity(max(0, min(15, int(args[0]))))

    # ── 0-15 level LED handlers ──────────────────────────────────────────
    def _h_level_set(self, args: list) -> None:
        if len(args) >= 3:
            x, y, lvl = int(args[0]), int(args[1]), int(args[2])
            self.device.led_set(x, y, max(0, min(15, lvl)))

    def _h_level_all(self, args: list) -> None:
        if args:
            self.device.led_all(max(0, min(15, int(args[0]))))

    def _h_level_map(self, args: list) -> None:
        # /grid/led/level/map x_off y_off l0..l63
        if len(args) >= 2 + 64:
            x_off, y_off = int(args[0]), int(args[1])
            vals = [max(0, min(15, int(a))) for a in args[2:2 + 64]]
            for r in range(8):
                self.device.led_row(x_off, y_off + r, vals[r * 8:(r + 1) * 8])

    def _h_level_row(self, args: list) -> None:
        # /grid/led/level/row x_off y l0 l1 ...
        if len(args) >= 3:
            x_off, y = int(args[0]), int(args[1])
            levels = [max(0, min(15, int(a))) for a in args[2:]]
            self.device.led_row(x_off, y, levels)

    def _h_level_col(self, args: list) -> None:
        # /grid/led/level/col x y_off l0 l1 ...
        if len(args) >= 3:
            x, y_off = int(args[0]), int(args[1])
            levels = [max(0, min(15, int(a))) for a in args[2:]]
            self.device.led_col(x, y_off, levels)

    # ── tilt ─────────────────────────────────────────────────────────────
    def _h_tilt_set(self, args: list) -> None:
        if len(args) >= 2:
            n, enable = int(args[0]), int(args[1])
            self.device.tilt_set(n, enable)

    # ── outbound (device -> client) ──────────────────────────────────────
    def _on_device_key(self, x: int, y: int, state: int) -> None:
        self._endpoint.send(self.host, self.app_port,
                            self.prefix + P.GRID_KEY, x, y, state)

    def _on_device_tilt(self, n: int, x: int, y: int, z: int) -> None:
        self._endpoint.send(self.host, self.app_port,
                            self.prefix + P.TILT, n, x, y, z)

    # ── for tests / GUI ──────────────────────────────────────────────────
    def update_destination(self, host: Optional[str] = None,
                           port: Optional[int] = None) -> None:
        if host is not None:
            self.host = host
        if port is not None:
            self.app_port = int(port)

    def set_prefix(self, prefix: str) -> None:
        new = P.normalize_prefix(prefix)
        if new == self.prefix:
            return
        old = self.prefix
        self.prefix = new
        self._endpoint.unregister_prefix(old)
        self._endpoint.register_prefix(self.prefix, self._h_prefix_dispatch)
        log.info("[%s] prefix %s -> %s (gui)", self.device.id, old, self.prefix)
