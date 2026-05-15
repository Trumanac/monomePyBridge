"""WebSocket bridge for a single grid device.

A small ``websockets`` server runs in its own thread (with its own
asyncio loop). Connected clients receive JSON-encoded device events and
may send LED commands back.

Outbound messages
-----------------
``{"type": "hello", "id": "<serial>", "type_name": "...", "width": W, "height": H}``
``{"type": "key",   "x": int, "y": int, "s": 0|1}``
``{"type": "tilt",  "n": int, "x": int, "y": int, "z": int}``

Inbound messages
----------------
``{"type": "led_set",   "x": int, "y": int, "level": 0..15}``
``{"type": "led_all",   "level": 0..15}``
``{"type": "led_row",   "x": int, "y": int, "levels": [0..15, ...]}``
``{"type": "led_col",   "x": int, "y": int, "levels": [0..15, ...]}``
``{"type": "intensity", "level": 0..15}``
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
from typing import Optional, Set

from ..bridge.base import Device, DeviceCallbacks

log = logging.getLogger("monomepybridge")


class WebSocketBridge:
    """Per-device WebSocket server."""

    def __init__(
        self,
        device: Device,
        host: str = "0.0.0.0",
        port: int = 0,
    ) -> None:
        self.device = device
        self.host = host
        self.port = int(port)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._clients: Set[object] = set()  # websockets.WebSocketServerProtocol
        self._cb: Optional[DeviceCallbacks] = None
        self._started_evt = threading.Event()
        self._start_error: Optional[BaseException] = None

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        try:
            import websockets  # noqa: F401
        except Exception as e:
            log.warning("WebSocket bridge unavailable (websockets import failed): %s", e)
            return
        self._thread = threading.Thread(
            target=self._thread_main, name=f"ws-{self.device.id}", daemon=True,
        )
        self._thread.start()
        if not self._started_evt.wait(timeout=5.0):
            log.warning("WebSocket bridge: failed to start within 5s")
            return
        if self._start_error is not None:
            log.warning("WebSocket bridge start error: %s", self._start_error)
            return
        self._cb = DeviceCallbacks(on_key=self._on_key, on_tilt=self._on_tilt)
        self.device.add_observer(self._cb)
        log.info("WebSocket bridge: %s:%d for %s", self.host, self.port, self.device.id)

    def stop(self) -> None:
        if self._cb is not None:
            try:
                self.device.remove_observer(self._cb)
            except Exception:
                pass
            self._cb = None
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._loop = None
        self._server = None
        self._clients.clear()
        log.info("WebSocket bridge stopped for %s", self.device.id)

    # ── server thread ────────────────────────────────────────────────────
    def _thread_main(self) -> None:
        import websockets

        async def boot() -> None:
            try:
                self._server = await websockets.serve(
                    self._handle_client, self.host, self.port,
                )
                # Resolve auto-allocated port.
                for sock in self._server.sockets or []:
                    self.port = sock.getsockname()[1]
                    break
            except Exception as e:
                self._start_error = e
                self._started_evt.set()
                return
            self._started_evt.set()

        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(boot())
            if self._start_error is None:
                loop.run_forever()
        finally:
            with contextlib.suppress(Exception):
                if self._server is not None:
                    self._server.close()
                    loop.run_until_complete(self._server.wait_closed())
            with contextlib.suppress(Exception):
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _handle_client(self, ws) -> None:
        self._clients.add(ws)
        try:
            await ws.send(json.dumps({
                "type": "hello",
                "id": self.device.id,
                "type_name": self.device.info.type_name,
                "width": self.device.width,
                "height": self.device.height,
            }))
            async for raw in ws:
                self._dispatch_inbound(raw)
        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            # When the last client drops, clear all device LEDs so the grid
            # does not stay frozen in whatever state the client left it in.
            if not self._clients:
                try:
                    self.device.led_all(0)
                except Exception:
                    log.debug("led_all(0) on client disconnect failed", exc_info=True)

    # ── outbound (called from device threads) ───────────────────────────
    def _broadcast(self, payload: dict) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        text = json.dumps(payload)

        async def _send_all() -> None:
            dead = []
            for ws in list(self._clients):
                try:
                    await ws.send(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

        try:
            asyncio.run_coroutine_threadsafe(_send_all(), loop)
        except Exception:
            pass

    def _on_key(self, x: int, y: int, s: int) -> None:
        self._broadcast({"type": "key", "x": int(x), "y": int(y), "s": int(s)})

    def _on_tilt(self, n: int, x: int, y: int, z: int) -> None:
        self._broadcast({
            "type": "tilt", "n": int(n),
            "x": int(x), "y": int(y), "z": int(z),
        })

    # ── inbound (runs on the asyncio loop) ──────────────────────────────
    def _dispatch_inbound(self, raw) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return
        if not isinstance(msg, dict):
            return
        t = msg.get("type")
        try:
            if t == "led_set":
                self.device.led_set(int(msg["x"]), int(msg["y"]),
                                    int(msg.get("level", 0)))
            elif t == "led_all":
                self.device.led_all(int(msg.get("level", 0)))
            elif t == "led_row":
                self.device.led_row(int(msg.get("x", 0)),
                                    int(msg["y"]),
                                    [int(v) for v in msg.get("levels", [])])
            elif t == "led_col":
                self.device.led_col(int(msg["x"]),
                                    int(msg.get("y", 0)),
                                    [int(v) for v in msg.get("levels", [])])
            elif t == "intensity":
                self.device.set_intensity(int(msg.get("level", 15)))
        except Exception:
            log.exception("ws inbound dispatch failed: %r", msg)
