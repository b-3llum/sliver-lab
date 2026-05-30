"""Multi-operator awareness.

sliver-server can have several operator clients connected at once. We surface
the roster (name + online status — the only fields sliver-py's Operator proto
carries) plus a `/me` endpoint so the frontend knows which operator this BFF is
without guessing.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException

from config import find_operator_config
from models import OperatorInfo, OperatorMe
from sliver_client import _pb_to_dict, hub

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/operators", tags=["operators"])


def _resolve_self_name() -> str:
    """This BFF's operator identity: the OPERATOR_NAME env override, else the
    `operator` field of the sliver-client config we loaded."""
    env = os.environ.get("OPERATOR_NAME")
    if env:
        return env
    try:
        from sliver import SliverClientConfig
        cfg = SliverClientConfig.parse_config_file(str(find_operator_config()))
        return str(getattr(cfg, "operator", "") or "")
    except Exception as e:  # noqa: BLE001 — config missing/unreadable; degrade to ""
        log.warning("could not resolve operator name from config: %s", e)
        return ""


@router.get("", response_model=list[OperatorInfo])
async def list_operators() -> list[OperatorInfo]:
    try:
        ops = await hub.client.operators()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    out: list[OperatorInfo] = []
    for o in ops:
        d = _pb_to_dict(o) or {}
        out.append(OperatorInfo(
            name=str(d.get("Name") or d.get("name", "")),
            online=bool(d.get("Online") or d.get("online") or False),
        ))
    return out


@router.get("/me", response_model=OperatorMe)
async def operator_me() -> OperatorMe:
    return OperatorMe(name=_resolve_self_name())
