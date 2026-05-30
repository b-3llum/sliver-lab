"""Session listing + per-session exec."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models import ExecRequest, ExecResponse, SessionInfo
from sliver_client import _pb_to_dict, hub

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _session_to_model(s) -> SessionInfo:
    d = _pb_to_dict(s) or {}
    # sliver-py uses different casing depending on version; normalize.
    return SessionInfo(
        ID=str(d.get("ID") or d.get("id") or ""),
        name=d.get("Name") or d.get("name", ""),
        hostname=d.get("Hostname") or d.get("hostname", ""),
        username=d.get("Username") or d.get("username", ""),
        uid=str(d.get("UID") or d.get("uid", "")),
        gid=str(d.get("GID") or d.get("gid", "")),
        os=d.get("OS") or d.get("os", ""),
        arch=d.get("Arch") or d.get("arch", ""),
        transport=d.get("Transport") or d.get("transport", ""),
        remote_address=d.get("RemoteAddress") or d.get("remote_address", ""),
        pid=int(d.get("PID") or d.get("pid") or 0),
        filename=d.get("Filename") or d.get("filename", ""),
        last_checkin=int(d.get("LastCheckin") or d.get("last_checkin") or 0),
        active_c2=d.get("ActiveC2") or d.get("active_c2", ""),
        is_dead=bool(d.get("IsDead") or d.get("is_dead") or False),
    )


@router.get("", response_model=list[SessionInfo])
async def list_sessions() -> list[SessionInfo]:
    try:
        sessions = await hub.client.sessions()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return [_session_to_model(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str) -> SessionInfo:
    try:
        sessions = await hub.client.sessions()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    for s in sessions:
        sid = str(getattr(s, "ID", None) or getattr(s, "id", ""))
        if sid == session_id:
            return _session_to_model(s)
    raise HTTPException(status_code=404, detail=f"session {session_id} not found")


@router.post("/{session_id}/exec", response_model=ExecResponse)
async def exec_cmd(session_id: str, req: ExecRequest) -> ExecResponse:
    """Backwards-compat alias. Delegates to /api/implants/{id}/exec under the
    hood so behaviour stays in lockstep with the unified surface."""
    from models import ImplantExecRequest
    from routes.implants import exec_implant
    argv = [req.cmd, *req.args]
    res = await exec_implant(session_id, ImplantExecRequest(argv=argv, timeout_s=req.timeout))
    # The unified handler returns SessionExecResponse for sessions, with
    # fields {stdout, stderr, exit_code, duration_ms}. Old shape used
    # {stdout, stderr, status, pid}. Map across.
    return ExecResponse(
        stdout=getattr(res, "stdout", "") or "",
        stderr=getattr(res, "stderr", "") or "",
        status=int(getattr(res, "exit_code", 0) or 0),
        pid=0,
    )


def _decode(v) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v if isinstance(v, str) else str(v)
