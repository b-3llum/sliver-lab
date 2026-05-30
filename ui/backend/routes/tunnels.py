"""Tunnels — portfwd / rportfwd / socks5 per session.

Session-only. Beacon attempts return a structured 400 directing the
operator to promote first. Implementation drives long-lived sliver-client
subprocesses via tunnel_registry; the BFF doesn't bind sockets directly.
"""
from __future__ import annotations

import ipaddress
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException

from models import (
    TunnelCreatePortfwd, TunnelCreateSocks5, TunnelList, TunnelRecord,
)
from routes.implants import _resolve
from tunnel_registry import TunnelEntry, TunnelKind, tunnel_registry

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/implants", tags=["tunnels"])

_BEACON_MSG = "tunnels require an interactive session; promote the beacon first"


# ── validation ─────────────────────────────────────────────────────


def _validate_port(p: int, field: str) -> None:
    if not (1 <= p <= 65535):
        raise HTTPException(status_code=400, detail=f"{field} must be in 1..65535")


def _validate_bind_addr(addr: str) -> None:
    if not addr:
        raise HTTPException(status_code=400, detail="bind_addr is required")
    try:
        ipaddress.ip_address(addr)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"bind_addr must be a valid IP (got {addr!r})",
        )


def _validate_remote_addr(addr: str) -> None:
    if not addr or not addr.strip():
        raise HTTPException(status_code=400, detail="remote_addr is required")


# ── entry → record projection ──────────────────────────────────────


def _entry_to_record(e: TunnelEntry) -> TunnelRecord:
    return TunnelRecord(
        id=e.id, kind=e.kind, session_id=e.session_id,
        bind_addr=e.bind_addr, bind_port=e.bind_port,
        remote_addr=e.remote_addr, remote_port=e.remote_port,
        started_at=e.started_at, marker_seen=e.marker_seen,
    )


# ── resolve helper ─────────────────────────────────────────────────


async def _require_session(implant_id: str) -> str:
    kind, _info = await _resolve(implant_id)
    if kind == "beacon":
        raise HTTPException(status_code=400, detail=_BEACON_MSG)
    return implant_id


# ── routes ─────────────────────────────────────────────────────────


@router.get("/{implant_id}/tunnels", response_model=TunnelList)
async def list_tunnels(implant_id: str) -> TunnelList:
    sid = await _require_session(implant_id)
    entries = tunnel_registry.list_for_session(sid)
    portfwds: list[TunnelRecord] = []
    rportfwds: list[TunnelRecord] = []
    socks: list[TunnelRecord] = []
    for e in entries:
        rec = _entry_to_record(e)
        if e.kind == "portfwd":
            portfwds.append(rec)
        elif e.kind == "rportfwd":
            rportfwds.append(rec)
        elif e.kind == "socks5":
            socks.append(rec)
    return TunnelList(portfwds=portfwds, rportfwds=rportfwds, socks5=socks)


async def _create_fwd(
    implant_id: str, kind: Literal["portfwd", "rportfwd"],
    req: TunnelCreatePortfwd,
) -> TunnelRecord:
    sid = await _require_session(implant_id)
    _validate_bind_addr(req.bind_addr)
    _validate_port(req.bind_port, "bind_port")
    _validate_remote_addr(req.remote_addr)
    _validate_port(req.remote_port, "remote_port")
    if tunnel_registry.has_bind(sid, req.bind_addr, req.bind_port):
        raise HTTPException(
            status_code=409,
            detail=f"tunnel already bound on {req.bind_addr}:{req.bind_port}",
        )
    try:
        entry = await tunnel_registry.register(
            kind, sid, req.bind_addr, req.bind_port,
            req.remote_addr, req.remote_port,
        )
    except RuntimeError as e:
        # Truncate raw output for client; full diagnostic in server log.
        log.warning("tunnel %s register failed: %s", kind, e)
        raise HTTPException(status_code=502, detail=str(e)[-2048:])
    return _entry_to_record(entry)


@router.post("/{implant_id}/portfwd", response_model=TunnelRecord)
async def create_portfwd(implant_id: str, req: TunnelCreatePortfwd) -> TunnelRecord:
    return await _create_fwd(implant_id, "portfwd", req)


@router.post("/{implant_id}/rportfwd", response_model=TunnelRecord)
async def create_rportfwd(implant_id: str, req: TunnelCreatePortfwd) -> TunnelRecord:
    return await _create_fwd(implant_id, "rportfwd", req)


@router.post("/{implant_id}/socks5", response_model=TunnelRecord)
async def create_socks5(implant_id: str, req: TunnelCreateSocks5) -> TunnelRecord:
    sid = await _require_session(implant_id)
    _validate_bind_addr(req.bind_addr)
    _validate_port(req.bind_port, "bind_port")
    if tunnel_registry.has_bind(sid, req.bind_addr, req.bind_port):
        raise HTTPException(
            status_code=409,
            detail=f"tunnel already bound on {req.bind_addr}:{req.bind_port}",
        )
    try:
        entry = await tunnel_registry.register(
            "socks5", sid, req.bind_addr, req.bind_port,
        )
    except RuntimeError as e:
        log.warning("tunnel socks5 register failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)[-2048:])
    return _entry_to_record(entry)


async def _delete_kind(implant_id: str, kind: TunnelKind, tunnel_id: str) -> dict:
    sid = await _require_session(implant_id)
    entry = tunnel_registry.get(tunnel_id)
    if entry is None or entry.session_id != sid or entry.kind != kind:
        raise HTTPException(status_code=404, detail=f"no {kind} with id {tunnel_id}")
    closed = await tunnel_registry.close(tunnel_id)
    return {"ok": closed, "id": tunnel_id}


@router.delete("/{implant_id}/portfwd/{tunnel_id}")
async def delete_portfwd(implant_id: str, tunnel_id: str):
    return await _delete_kind(implant_id, "portfwd", tunnel_id)


@router.delete("/{implant_id}/rportfwd/{tunnel_id}")
async def delete_rportfwd(implant_id: str, tunnel_id: str):
    return await _delete_kind(implant_id, "rportfwd", tunnel_id)


@router.delete("/{implant_id}/socks5/{tunnel_id}")
async def delete_socks5(implant_id: str, tunnel_id: str):
    return await _delete_kind(implant_id, "socks5", tunnel_id)
