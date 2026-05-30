"""Listener lifecycle + persistent-row escape hatch.

Live listeners come from sliver-py's `jobs()`. Persistent listener config
lives in sliver.db; we expose read/delete on those rows so the operator can
recover from "port in use" errors caused by stale persisted rows after a
teamserver crash.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import closing

import grpc
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from config import SLIVER_DB_PATH
from models import JobInfo, ListenerConflict, ListenerCreate, PersistentListener
from sliver_client import _pb_to_dict, hub

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/listeners", tags=["listeners"])

# sliver-server's Job.Name is the listener kind ("mtls", "http", "https",
# "dns", "wg"); Job.Protocol is the wire protocol ("tcp"/"udp") which is
# *not* what we want to filter on. Keep both, but match on Name first.
LISTENER_KINDS = {"http", "https", "mtls", "dns", "wg"}

# sliver.db kind → table name. http_listeners stores both "http" and "https"
# rows (the `secure` column distinguishes them).
_KIND_TABLES: dict[str, str] = {
    "mtls": "mtls_listeners",
    "http": "http_listeners",
    "https": "http_listeners",
    "dns": "dns_listeners",
    "wg": "wg_listeners",
    "multiplayer": "multiplayer_listeners",
}


def _parse_domains(v) -> list[str]:
    """Sliver's pb stringifies Domains as "[]" or "[a.com b.com]". When the
    field reaches us as a string, iterating it yields characters instead of
    domains. Normalize: pass through real sequences, strip brackets and
    whitespace-split strings, drop empties."""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(d) for d in v if str(d).strip()]
    if isinstance(v, str):
        inner = v.strip()
        if inner.startswith("[") and inner.endswith("]"):
            inner = inner[1:-1]
        return [tok for tok in inner.split() if tok]
    return []


def _job_to_model(j) -> JobInfo:
    d = _pb_to_dict(j) or {}
    return JobInfo(
        ID=int(d.get("ID") or d.get("id") or 0),
        name=d.get("Name") or d.get("name", ""),
        description=d.get("Description") or d.get("description", ""),
        protocol=d.get("Protocol") or d.get("protocol", ""),
        port=int(d.get("Port") or d.get("port") or 0),
        domains=_parse_domains(d.get("Domains") or d.get("domains")),
    )


@router.get("", response_model=list[JobInfo])
async def list_listeners() -> list[JobInfo]:
    try:
        jobs = await hub.client.jobs()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    # Single registry read, joined by port — no N+1. (Phase E.)
    from ngrok_registry import registry as ngrok_reg
    exposures = {t.listener_port: t for t in ngrok_reg.list()}
    out: list[JobInfo] = []
    for j in jobs:
        m = _job_to_model(j)
        name_l = (m.name or "").lower()
        if name_l in LISTENER_KINDS or "listener" in name_l:
            m.public_exposure = exposures.get(m.port)
            out.append(m)
    return out


def _looks_like_already_exists(exc: Exception) -> bool:
    """sliver-py occasionally wraps the gRPC error in a generic Exception
    (text body preserved). Belt-and-braces matcher."""
    if isinstance(exc, grpc.aio.AioRpcError) and exc.code() == grpc.StatusCode.ALREADY_EXISTS:
        return True
    return "in use" in str(exc).lower() or "already" in str(exc).lower()


@router.post("", response_model=JobInfo, responses={409: {"model": ListenerConflict}})
async def start_listener(req: ListenerCreate) -> JobInfo:
    try:
        c = hub.client
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        if req.kind == "http":
            job = await c.start_http_listener(host=req.host, port=req.port, website=req.website or "", persistent=req.persistent)
        elif req.kind == "https":
            job = await c.start_https_listener(host=req.host, port=req.port, website=req.website or "", persistent=req.persistent)
        elif req.kind == "mtls":
            job = await c.start_mtls_listener(host=req.host, port=req.port, persistent=req.persistent)
        elif req.kind == "dns":
            if not req.domain:
                raise HTTPException(status_code=400, detail="dns listener requires 'domain'")
            job = await c.start_dns_listener(domains=[req.domain], canaries=False, host=req.host, port=req.port, persistent=req.persistent)
        else:
            raise HTTPException(status_code=400, detail=f"unsupported listener kind: {req.kind}")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        if _looks_like_already_exists(e):
            conflict = ListenerConflict(
                kind=req.kind,
                host=req.host,
                port=req.port,
                message=f"port {req.port} is in use",
                hint=("Likely a stale row in sliver.db from a previous teamserver "
                      "run. List orphans at GET /api/listeners/persistent and "
                      "remove the entry via DELETE /api/listeners/persistent/{job_id}."),
            )
            raise HTTPException(status_code=409, detail=conflict.model_dump())
        raise HTTPException(status_code=500, detail=f"start_listener failed: {e}")
    return _job_to_model(job)


# NOTE: this must be declared *before* DELETE /{job_id} — the int path param
# otherwise greedily matches the literal segment "persistent" and 422s before
# this handler is ever reached. The persistent-section helpers it calls
# (_list_persistent_sync / _forget_persistent_sync / _live_job_ids) are
# module-level and resolved at call time, so the forward reference is fine.
@router.delete("/persistent")
async def forget_all_persistent_listeners():
    """Bulk-forget every orphaned persistent row (those with no live job),
    running the per-row delete logic in a loop. Mirrors GET /persistent's
    orphan filter so it only clears what that section shows. Returns
    {deleted_count, errors}; status 207 if any row failed, else 200."""
    if not SLIVER_DB_PATH.is_file():
        raise HTTPException(status_code=503, detail=f"sliver.db not found at {SLIVER_DB_PATH}")
    try:
        rows = await asyncio.to_thread(_list_persistent_sync, str(SLIVER_DB_PATH))
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"sliver.db read failed: {e}")
    live = await _live_job_ids()
    targets = [r.job_id for r in rows if not live or r.job_id not in live]
    deleted = 0
    errors: list[dict] = []
    for jid in targets:
        try:
            await asyncio.to_thread(_forget_persistent_sync, str(SLIVER_DB_PATH), jid)
            deleted += 1
        except KeyError:
            errors.append({"job_id": jid, "error": "not found"})
        except (ValueError, sqlite3.Error) as e:  # noqa: BLE001
            errors.append({"job_id": jid, "error": str(e)})
    log.info("bulk forget persistent listeners: %d deleted, %d error(s)", deleted, len(errors))
    payload = {"deleted_count": deleted, "errors": errors}
    if errors:
        return JSONResponse(payload, status_code=207)
    return payload


@router.delete("/{job_id}")
async def stop_listener(job_id: int) -> dict:
    try:
        await hub.client.kill_job(job_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"kill_job failed: {e}")
    return {"ok": True, "id": job_id}


# ── Persistent (orphaned) listener endpoints ───────────────────────

def _list_persistent_sync(db_path: str) -> list[PersistentListener]:
    """Read all persisted listener rows. Runs in a thread; sqlite is blocking."""
    out: list[PersistentListener] = []
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        for kind, table in _KIND_TABLES.items():
            try:
                cur = conn.execute(
                    f"SELECT lj.job_id, lj.type, lj.created_at, t.host, t.port "
                    f"FROM listener_jobs lj JOIN {table} t ON t.listener_job_id = lj.id "
                    f"WHERE lj.type = ?",
                    (kind,),
                )
            except sqlite3.OperationalError as e:
                # Schema drift — log and skip this kind rather than 500ing.
                log.warning("persistent listener query failed for %s: %s", kind, e)
                continue
            for row in cur.fetchall():
                out.append(PersistentListener(
                    job_id=int(row["job_id"]),
                    kind=str(row["type"]),
                    host=str(row["host"] or ""),
                    port=int(row["port"] or 0),
                    created_at=str(row["created_at"]) if row["created_at"] else None,
                ))
    return out


def _forget_persistent_sync(db_path: str, job_id: int) -> str:
    """Delete the listener_jobs row and its kind-specific child row inside one
    transaction. Returns the kind for caller logging. Raises KeyError on miss."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, type FROM listener_jobs WHERE job_id = ?", (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(job_id)
        listener_uuid = row["id"]
        kind = row["type"]
        table = _KIND_TABLES.get(kind)
        if table is None:
            raise ValueError(f"unknown persisted listener kind: {kind!r}")
        with conn:  # implicit transaction
            conn.execute(f"DELETE FROM {table} WHERE listener_job_id = ?", (listener_uuid,))
            conn.execute("DELETE FROM listener_jobs WHERE id = ?", (listener_uuid,))
    return kind


async def _live_job_ids() -> set[int]:
    """IDs of jobs currently bound by sliver-server. Empty set if the server
    is unreachable — callers fall back to unfiltered output, since orphans
    matter most when the server isn't up."""
    try:
        jobs = await hub.client.jobs()
    except Exception as e:  # noqa: BLE001 — includes RuntimeError (no conn) + grpc errors
        log.warning("persistent listener filter falling back: cannot read live jobs (%s)", e)
        return set()
    ids: set[int] = set()
    for j in jobs:
        d = _pb_to_dict(j) or {}
        try:
            ids.add(int(d.get("ID") or d.get("id") or 0))
        except (TypeError, ValueError):
            continue
    ids.discard(0)
    return ids


@router.get("/persistent", response_model=list[PersistentListener])
async def list_persistent_listeners() -> list[PersistentListener]:
    if not SLIVER_DB_PATH.is_file():
        raise HTTPException(status_code=503, detail=f"sliver.db not found at {SLIVER_DB_PATH}")
    try:
        rows = await asyncio.to_thread(_list_persistent_sync, str(SLIVER_DB_PATH))
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"sliver.db read failed: {e}")
    live = await _live_job_ids()
    if not live:
        return rows
    return [r for r in rows if r.job_id not in live]


@router.delete("/persistent/{job_id}")
async def forget_persistent_listener(job_id: int) -> dict:
    if not SLIVER_DB_PATH.is_file():
        raise HTTPException(status_code=503, detail=f"sliver.db not found at {SLIVER_DB_PATH}")
    try:
        kind = await asyncio.to_thread(_forget_persistent_sync, str(SLIVER_DB_PATH), job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no persistent listener with job_id {job_id}")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"sliver.db delete failed: {e}")
    log.info("forget persistent listener job_id=%s kind=%s", job_id, kind)
    return {"ok": True, "job_id": job_id, "kind": kind}
