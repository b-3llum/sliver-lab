"""Sliver loot store."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models import LootInfo
from sliver_client import _pb_to_dict, hub

router = APIRouter(prefix="/api/loot", tags=["loot"])


@router.get("", response_model=list[LootInfo])
async def list_loot() -> list[LootInfo]:
    try:
        loot = await hub.client.loot_all()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AttributeError:
        return []  # older sliver-py
    out: list[LootInfo] = []
    for item in loot or []:
        d = _pb_to_dict(item) or {}
        out.append(LootInfo(
            ID=str(d.get("ID") or d.get("id") or ""),
            name=d.get("Name") or d.get("name", ""),
            type=str(d.get("Type") or d.get("type", "")),
            file_type=str(d.get("FileType") or d.get("file_type", "")),
            credential_type=str(d.get("CredentialType") or d.get("credential_type", "")),
        ))
    return out
