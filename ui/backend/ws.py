"""/events WebSocket endpoint.

Browsers connect, get every event from the Sliver event bus + BFF lifecycle
messages. Topic filtering is done client-side; payloads are small.

We also emit a tiny `{"type":"graph_dirty"}` envelope whenever an event
arrives that could change the C2 topology (sessions/beacons/jobs). The
Graph view debounces these and re-fetches /api/graph.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth import verify_ws_token
from sliver_client import hub

log = logging.getLogger(__name__)
router = APIRouter()

_GRAPH_DIRTY_PREFIXES: tuple[str, ...] = ("session", "beacon", "job")


def _is_graph_dirty(event_type: str) -> bool:
    """Match sliver event names like session-connected, beacon-registered,
    job-stopped. Skip BFF lifecycle events (bff:*) so a reconnect doesn't
    spam graph refreshes."""
    if not event_type or event_type.startswith("bff:"):
        return False
    return any(event_type.startswith(p) for p in _GRAPH_DIRTY_PREFIXES)


@router.websocket("/events")
async def events_ws(ws: WebSocket) -> None:
    # Token rides as a query param (browsers can't set headers on a WS upgrade).
    # We accept() first, then close(1008): a pre-accept close is surfaced by
    # real ASGI servers as an HTTP 403 with no close code, but the browser only
    # sees a usable close code (1008) once the handshake has completed. So
    # accept, then immediately close with the policy-violation code.
    if not verify_ws_token(ws.query_params.get("token")):
        await ws.accept()
        await ws.close(code=1008, reason="missing or invalid token")
        return
    await ws.accept()
    client = ws.client.host if ws.client else "?"
    log.info("client connected %s", client)
    q = hub.subscribe()
    # send initial state snapshot
    await ws.send_json({"type": "bff:state", "data": hub.state().model_dump()})
    try:
        while True:
            payload = await q.get()
            await ws.send_json(payload)
            if _is_graph_dirty(payload.get("type", "")):
                await ws.send_json({"type": "graph_dirty"})
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("WS dropped: %s", e)
    finally:
        hub.unsubscribe(q)
        log.info("client disconnected %s", client)
