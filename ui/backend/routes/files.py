"""Per-session file ops: ls, cat-like download.

Only session-scoped for v1 (no beacon variant). Uploads are kept minimal.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException

from models import FileEntry, FileListResponse
from sliver_client import _pb_to_dict, hub

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/{session_id}", response_model=FileListResponse)
async def list_dir(session_id: str, path: str = ".") -> FileListResponse:
    try:
        iact = await hub.client.interact_session(session_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"interact failed: {e}")
    try:
        result = await iact.ls(path)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"ls failed: {e}")
    d = _pb_to_dict(result) or {}
    raw = d.get("Files") or d.get("files") or []
    entries: list[FileEntry] = []
    for f in raw:
        fd = _pb_to_dict(f) if hasattr(f, "DESCRIPTOR") else f
        entries.append(FileEntry(
            name=fd.get("Name") or fd.get("name", ""),
            size=int(fd.get("Size") or fd.get("size") or 0),
            mode=fd.get("Mode") or fd.get("mode", ""),
            mod_time=int(fd.get("ModTime") or fd.get("mod_time") or 0),
            is_dir=bool(fd.get("IsDir") or fd.get("is_dir") or False),
        ))
    return FileListResponse(path=d.get("Path") or d.get("path") or path, entries=entries)


@router.get("/{session_id}/download")
async def download(session_id: str, path: str) -> dict:
    """Returns base64 content. Frontend decodes for binary-safe transit."""
    try:
        iact = await hub.client.interact_session(session_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"interact failed: {e}")
    try:
        result = await iact.download(path)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"download failed: {e}")
    d = _pb_to_dict(result) or {}
    data = d.get("Data") or d.get("data") or b""
    if isinstance(data, str):
        data = data.encode()
    return {
        "path": path,
        "size": len(data),
        "b64": base64.b64encode(data).decode("ascii"),
    }
