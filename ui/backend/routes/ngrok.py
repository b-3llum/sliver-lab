"""ngrok public-exposure routes (Phase E).

Open / list / close ngrok TCP tunnels that front local sliver listener ports.
Guarded by the global auth dependency (applied at router include in main.py).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from config import ngrok_authtoken
from models import NgrokCreateRequest, NgrokTunnel
from ngrok_registry import (
    NgrokDisabled, NgrokDuplicate, NgrokStartError, registry,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ngrok", tags=["ngrok"])

_NO_TOKEN_DETAIL = "set NGROK_AUTHTOKEN in backend/.env to enable ngrok"


async def _active_listener_ports() -> set[int]:
    """Ports currently bound by a live listener job. We only expose real
    listeners — never an arbitrary port (no orphan exposure)."""
    from routes.listeners import list_listeners
    jobs = await list_listeners()
    return {j.port for j in jobs if j.port}


@router.get("", response_model=list[NgrokTunnel])
async def list_ngrok() -> list[NgrokTunnel]:
    return registry.list()


@router.post("", response_model=NgrokTunnel)
async def create_ngrok(req: NgrokCreateRequest) -> NgrokTunnel:
    if not ngrok_authtoken():
        raise HTTPException(status_code=503, detail=_NO_TOKEN_DETAIL)
    if req.listener_port not in await _active_listener_ports():
        raise HTTPException(
            status_code=400,
            detail=f"no active listener on port {req.listener_port}",
        )
    try:
        return await registry.start(req.listener_port)
    except NgrokDisabled:
        raise HTTPException(status_code=503, detail=_NO_TOKEN_DETAIL)
    except NgrokDuplicate as e:
        raise HTTPException(
            status_code=409,
            detail=f"port {req.listener_port} is already exposed at {e.existing.public_url}",
        )
    except NgrokStartError as e:
        raise HTTPException(status_code=502, detail=f"ngrok failed: {e}")


@router.delete("/{tunnel_id}")
async def delete_ngrok(tunnel_id: str) -> dict:
    try:
        await registry.stop(tunnel_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no ngrok tunnel {tunnel_id}")
    return {"ok": True}
