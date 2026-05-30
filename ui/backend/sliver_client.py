"""Singleton sliver-py client with reconnect + event fanout.

One upstream subscription to Sliver's event bus is multiplexed to N browser
WebSockets via an asyncio.Queue per subscriber.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sliver import SliverClient, SliverClientConfig

from config import (
    EVENT_BUFFER_SIZE,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    find_operator_config,
)
from models import ConnState

log = logging.getLogger(__name__)


class SliverHub:
    """Wraps the sliver-py client and pumps its event bus to subscribers."""

    def __init__(self) -> None:
        self._client: SliverClient | None = None
        self._cfg_path: str | None = None
        self._server_version: str | None = None
        self._connected = False
        self._last_error: str | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task | None = None
        self._event_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # ── lifecycle ────────────────────────────────────────────────
    async def start(self) -> None:
        self._stop.clear()
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def stop(self) -> None:
        self._stop.set()
        for t in (self._event_task, self._reconnect_task):
            if t and not t.done():
                t.cancel()
        self._client = None
        self._connected = False

    # ── connection ───────────────────────────────────────────────
    async def _connect_once(self) -> None:
        cfg_path = find_operator_config()
        self._cfg_path = str(cfg_path)
        config = SliverClientConfig.parse_config_file(str(cfg_path))
        client = SliverClient(config)
        version = await client.connect()
        self._client = client
        self._server_version = str(version) if version else None
        self._connected = True
        self._last_error = None
        log.info("Connected to Sliver teamserver (%s)", self._server_version)

    async def _reconnect_loop(self) -> None:
        delay = RECONNECT_INITIAL_DELAY
        while not self._stop.is_set():
            try:
                if not self._connected:
                    await self._connect_once()
                    delay = RECONNECT_INITIAL_DELAY
                    self._event_task = asyncio.create_task(self._pump_events())
                # idle — wait until event loop exits (disconnect) or stop
                while self._connected and not self._stop.is_set():
                    await asyncio.sleep(1.0)
            except Exception as e:  # noqa: BLE001
                self._connected = False
                self._last_error = f"{type(e).__name__}: {e}"
                log.warning("Sliver connect failed: %s (retry in %.1fs)", e, delay)
                await self._broadcast({"type": "bff:disconnected", "data": {"error": self._last_error}})
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, RECONNECT_MAX_DELAY)

    async def _pump_events(self) -> None:
        assert self._client is not None
        try:
            await self._broadcast({"type": "bff:connected", "data": {"version": self._server_version}})
            async for event in self._client.events():
                # event is a protobuf Event message
                payload = {
                    "type": getattr(event, "EventType", "unknown"),
                    "data": {
                        "session": _pb_to_dict(getattr(event, "Session", None)),
                        "beacon": _pb_to_dict(getattr(event, "Beacon", None)),
                        "job": _pb_to_dict(getattr(event, "Job", None)),
                        "client": _pb_to_dict(getattr(event, "Client", None)),
                        "data": _try_decode(getattr(event, "Data", b"")),
                        "err": getattr(event, "Err", ""),
                    },
                }
                await self._broadcast(payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Event stream died: %s", e)
            self._last_error = f"{type(e).__name__}: {e}"
        finally:
            self._connected = False

    # ── subscriber fanout ───────────────────────────────────────
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=EVENT_BUFFER_SIZE)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    # ── accessors ───────────────────────────────────────────────
    @property
    def client(self) -> SliverClient:
        if not self._client or not self._connected:
            raise RuntimeError("Sliver client not connected")
        return self._client

    def state(self) -> ConnState:
        return ConnState(
            connected=self._connected,
            server_version=self._server_version,
            cfg_path=self._cfg_path,
            last_error=self._last_error,
        )


def _pb_to_dict(msg: Any) -> dict[str, Any] | None:
    """Best-effort protobuf → dict. Returns None for falsy / missing."""
    if msg is None:
        return None
    # Heuristic: protobuf messages have DESCRIPTOR; if so, walk fields.
    if hasattr(msg, "DESCRIPTOR"):
        out: dict[str, Any] = {}
        try:
            for fd in msg.DESCRIPTOR.fields:
                v = getattr(msg, fd.name, None)
                if v in (None, "", 0, b"", False):
                    continue
                if isinstance(v, bytes):
                    out[fd.name] = _try_decode(v)
                else:
                    out[fd.name] = v if _is_jsonable(v) else str(v)
            return out or None
        except Exception:  # noqa: BLE001
            return None
    return None


def _try_decode(b: Any) -> str:
    if isinstance(b, bytes):
        try:
            return b.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return repr(b)
    return b if isinstance(b, str) else ""


def _is_jsonable(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool, list, dict))


hub = SliverHub()
