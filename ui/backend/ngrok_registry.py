"""In-process ngrok tunnel registry (Phase E).

Opens ngrok TCP tunnels fronting local sliver listener ports so implants can
call back from any network. Uses the official `ngrok` Python SDK (ngrok-rust
binding) — tunnels live in *this* process and die with it, so unlike Phase 5's
sliver-client subprocesses there are no cross-restart orphans to reap.

The SDK is referenced through the module-level `ngrok` name so tests can swap
it out (monkeypatch ngrok_registry.ngrok) without touching the network.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import ngrok  # patched at the module boundary in tests

from config import ngrok_authtoken
from models import NgrokTunnel

log = logging.getLogger(__name__)

_START_TIMEOUT_S = 15.0


class NgrokDisabled(Exception):
    """NGROK_AUTHTOKEN is not set."""


class NgrokDuplicate(Exception):
    """A tunnel already exposes this listener port."""
    def __init__(self, existing: NgrokTunnel):
        self.existing = existing


class NgrokStartError(Exception):
    """ngrok failed to open the tunnel (incl. 15s timeout)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _Entry:
    record: NgrokTunnel
    # Both are retained: the Session keeps the agent connection alive (drop it
    # and the tunnel closes), the Listener is the tunnel we close on stop.
    session: object   # ngrok.Session
    listener: object  # ngrok.Listener


class NgrokRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def list(self) -> list[NgrokTunnel]:
        return [e.record for e in self._entries.values()]

    def by_port(self, port: int) -> NgrokTunnel | None:
        for e in self._entries.values():
            if e.record.listener_port == port:
                return e.record
        return None

    async def _open(self, token: str, upstream: str):
        """ngrok-python 1.7 async builder pattern (verified against the SDK):
        a Session, then a TCP endpoint that listens publicly and forwards to the
        local upstream. NOT ngrok.async_connect() — that takes a single config
        object, while (addr, proto, **opts) belongs to the *sync* connect/forward."""
        session = await ngrok.SessionBuilder().authtoken(token).connect()
        try:
            listener = await session.tcp_endpoint().listen_and_forward(upstream)
        except Exception:
            # Tear down the half-open session if the listener fails.
            try:
                await session.close()
            except Exception:  # noqa: BLE001
                pass
            raise
        return session, listener

    async def start(self, listener_port: int) -> NgrokTunnel:
        token = ngrok_authtoken()
        if not token:
            raise NgrokDisabled()
        existing = self.by_port(listener_port)
        if existing is not None:
            raise NgrokDuplicate(existing)

        upstream = f"tcp://localhost:{listener_port}"
        try:
            session, listener = await asyncio.wait_for(
                self._open(token, upstream), timeout=_START_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            raise NgrokStartError(f"ngrok did not surface a public URL within {int(_START_TIMEOUT_S)}s")
        except Exception as e:  # noqa: BLE001 — surface as a clean error to the route
            raise NgrokStartError(str(e))

        url = listener.url()
        parsed = urlparse(url)
        rec = NgrokTunnel(
            id=str(uuid.uuid4()),
            listener_port=listener_port,
            public_url=url,
            public_host=parsed.hostname or "",
            public_port=int(parsed.port or 0),
            kind="tcp",
            started_at=_now_iso(),
        )
        self._entries[rec.id] = _Entry(record=rec, session=session, listener=listener)
        log.info("ngrok tunnel %s up: %s → localhost:%d", rec.id, url, listener_port)
        return rec

    async def stop(self, tunnel_id: str) -> None:
        entry = self._entries.pop(tunnel_id, None)
        if entry is None:
            raise KeyError(tunnel_id)
        for closer in (entry.listener.close, entry.session.close):
            try:
                await closer()
            except Exception as e:  # noqa: BLE001 — already removed; log + move on
                log.warning("ngrok stop %s: %s", tunnel_id, e)
        log.info("ngrok tunnel %s stopped", tunnel_id)

    async def close_all(self) -> None:
        for tid in list(self._entries):
            try:
                await self.stop(tid)
            except Exception as e:  # noqa: BLE001
                log.warning("ngrok close_all: %s", e)
        # Belt-and-braces: tear down the whole agent session.
        try:
            ngrok.kill()
        except Exception:  # noqa: BLE001
            pass


registry = NgrokRegistry()
