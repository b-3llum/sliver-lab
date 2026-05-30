"""Unified per-implant action surface.

Each route accepts either a session_id or a beacon_id and branches on the
underlying kind. Sessions are interactive (synchronous response). Beacons
are async — the route queues an asyncio.Task into the in-process registry
and returns a task_id; the browser tracks state via /api/tasks/{id} and the
WS `task_update` envelope.

We never block the request handler on a beacon's next check-in. We use
sliver-py's interact_beacon().{execute,ls,screenshot,...} inside a
background task and let it await as long as it needs.
"""
from __future__ import annotations

import gzip
import logging
import time
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from models import (
    BeaconTaskResponse, ImplantCapabilities, ImplantExecRequest, ImplantInfo,
    ImplantLsRequest, ImplantPathRequest, SessionExecResponse,
    SessionUploadResponse, TaskQueuedResponse,
)
from sliver_client import _pb_to_dict, hub
from task_registry import registry
from routes.sessions import _session_to_model
from routes.beacons import _beacon_to_model

# Imported lazily inside the helper so test environments that monkey-patch
# sliver-py don't need it eagerly resolved at module load time.
try:
    from sliver.pb.sliverpb import sliver_pb2 as _sliver_pb2
except Exception:  # noqa: BLE001 — surface in the route as a 503 instead
    _sliver_pb2 = None  # type: ignore[assignment]

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/implants", tags=["implants"])


# ── ID resolution ──────────────────────────────────────────────────

async def _resolve(implant_id: str) -> tuple[str, dict[str, Any]]:
    """Find which kind (session vs beacon) an ID belongs to. Returns the
    canonical-form info dict for the implant. Raises 404 if not found."""
    try:
        sessions = await hub.client.sessions()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    for s in sessions:
        sid = str(getattr(s, "ID", None) or getattr(s, "id", None) or "")
        if sid == implant_id:
            return "session", _session_to_model(s).model_dump(by_alias=True)
    try:
        beacons = await hub.client.beacons()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    for b in beacons:
        bid = str(getattr(b, "ID", None) or getattr(b, "id", None) or "")
        if bid == implant_id:
            return "beacon", _beacon_to_model(b).model_dump(by_alias=True)
    raise HTTPException(status_code=404, detail=f"no implant with id {implant_id}")


def _capabilities(kind: str) -> ImplantCapabilities:
    # Sessions can run an interactive shell; beacons can't. Otherwise the
    # capability surface is the same and the route handler hides the async
    # nature behind a task_id. Only beacons can be promoted via /interactive.
    return ImplantCapabilities(
        interactive=(kind == "session"),
        promote_to_session=(kind == "beacon"),
        tunneling=(kind == "session"),
    )


# ── Info ───────────────────────────────────────────────────────────

@router.get("/{implant_id}/info", response_model=ImplantInfo)
async def get_info(implant_id: str) -> ImplantInfo:
    kind, info = await _resolve(implant_id)
    return ImplantInfo(kind=kind, info=info, capabilities=_capabilities(kind))  # type: ignore[arg-type]


# ── Result-shape helpers ───────────────────────────────────────────

def _exec_result_dict(result: Any) -> dict[str, Any]:
    d = _pb_to_dict(result) or {}
    stdout = d.get("Stdout") or d.get("stdout") or b""
    stderr = d.get("Stderr") or d.get("stderr") or b""
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", "replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    status = int(d.get("Status") or d.get("status") or 0)
    return {"stdout": stdout, "stderr": stderr, "exit_code": status}


def _proto_children(result: Any, attr: str, dict_keys: tuple[str, ...]) -> list[Any]:
    """Pull a list of child items out of `result`, which may be:

      - a bare ``list`` (sliver-py's InteractiveSession.ps() returns
        ``list(processes.Processes)`` directly),
      - a ``dict`` (already decoded, e.g. the monkeypatched test fakes),
      - a protobuf message with a repeated ``attr`` field.

    The repeated field is read via ``getattr`` rather than going through
    ``_pb_to_dict`` because ``_pb_to_dict`` stringifies repeated message
    fields (``str(container)``) — so ``d["Files"]`` / ``d["Processes"]`` come
    back as text, not a list, and the entries silently vanish.
    """
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for k in dict_keys:
            v = result.get(k)
            if v:
                return list(v) if not isinstance(v, str) else []
        return []
    v = getattr(result, attr, None)
    if v:
        try:
            return list(v)
        except TypeError:
            return []
    return []


def _proto_scalars(result: Any) -> dict[str, Any]:
    """Top-level scalar fields of `result` (repeated fields are ignored here —
    use _proto_children for those). Safe for proto, dict, or list inputs."""
    if isinstance(result, dict):
        return result
    return _pb_to_dict(result) or {}


def _ls_result_dict(result: Any) -> dict[str, Any]:
    raw = _proto_children(result, "Files", ("Files", "files"))
    entries: list[dict[str, Any]] = []
    for f in raw:
        fd = _pb_to_dict(f) if hasattr(f, "DESCRIPTOR") else f
        if not isinstance(fd, dict):
            continue
        entries.append({
            "name": fd.get("Name") or fd.get("name", ""),
            "size": int(fd.get("Size") or fd.get("size") or 0),
            "mode": fd.get("Mode") or fd.get("mode", ""),
            "mod_time": int(fd.get("ModTime") or fd.get("mod_time") or 0),
            "is_dir": bool(fd.get("IsDir") or fd.get("is_dir") or False),
        })
    d = _proto_scalars(result)
    return {"path": d.get("Path") or d.get("path") or "", "entries": entries}


def _ps_result_dict(result: Any) -> dict[str, Any]:
    raw = _proto_children(result, "Processes", ("Processes", "processes"))
    procs: list[dict[str, Any]] = []
    for p in raw:
        pd = _pb_to_dict(p) if hasattr(p, "DESCRIPTOR") else p
        if not isinstance(pd, dict):
            continue
        procs.append({
            "pid": int(pd.get("Pid") or pd.get("pid") or 0),
            "ppid": int(pd.get("Ppid") or pd.get("ppid") or 0),
            "name": pd.get("Executable") or pd.get("name") or pd.get("Name", ""),
            "owner": pd.get("Owner") or pd.get("owner", ""),
        })
    return {"processes": procs}


def _raw_data_bytes(result: Any) -> bytes:
    """Pull the raw `.Data` bytes off a proto WITHOUT going through
    _pb_to_dict — that helper decodes bytes fields via
    `.decode('utf-8', errors='replace')`, which corrupts any binary payload
    (e.g. PNG magic 0x89 → U+FFFD 0xEF 0xBF 0xBD). Reading the field directly
    keeps bytes as bytes the whole way to the /result response."""
    if isinstance(result, dict):
        data = result.get("Data") or result.get("data") or b""
    else:
        data = getattr(result, "Data", None)
        if data is None:
            data = getattr(result, "data", b"")
    if isinstance(data, str):
        # Defensive: already-decoded text → round-trip losslessly to bytes.
        return data.encode("utf-8", "surrogatepass")
    return data or b""


def _download_bytes(result: Any) -> bytes:
    """Sliver gzip-encodes file downloads and tags them Encoder='gzip'. Decode
    so the operator gets the real file, not a gzip stream. (Screenshots are
    raw PNG — no Encoder — so _screenshot_bytes leaves them untouched.)"""
    data = _raw_data_bytes(result)
    if isinstance(result, dict):
        encoder = str(result.get("Encoder") or result.get("encoder") or "")
    else:
        encoder = str(getattr(result, "Encoder", "") or "")
    if encoder.lower() == "gzip" and data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data)
        except OSError:
            return data  # not a valid gzip stream after all — hand back raw
    return data


def _screenshot_bytes(result: Any) -> bytes:
    return _raw_data_bytes(result)


# ── Generic queue-for-beacon runner ────────────────────────────────

async def _watch_sent_to_beacon(
    local_task_id: str, beacon_id: str, sliver_task_id: str | None,
    queued_future,
) -> None:
    """Poll Sliver's per-beacon task list for our task's SentAt → when it
    becomes non-zero (or its State string flips to 'sent'), transition the
    local registry entry from queued → running. Sliver-py doesn't surface a
    distinct 'task-sent' event, so polling on a 3 s cadence is the cheapest
    reliable signal. Stops on its own once the result future resolves."""
    import asyncio
    if not sliver_task_id:
        return
    while not queued_future.done():
        try:
            # sliver-py's client.beacon_tasks returns a list[BeaconTask] —
            # the .Tasks unwrap is done inside the SDK call.
            tasks = await hub.client.beacon_tasks(beacon_id)
            for t in tasks:
                if getattr(t, "ID", "") != sliver_task_id:
                    continue
                sent_at = getattr(t, "SentAt", 0) or 0
                state_str = (getattr(t, "State", "") or "").lower()
                if sent_at > 0 or state_str == "sent":
                    registry.set_running(local_task_id)
                    return
        except Exception:  # noqa: BLE001 — transient gRPC error; keep trying
            pass
        try:
            await asyncio.sleep(3.0)
        except asyncio.CancelledError:
            return


async def _run_beacon_task(
    implant_id: str, action: str,
    call,                       # async callable taking InteractiveBeacon
    extract,                    # callable mapping raw result → dict
    result_kind: str,
    *,
    as_bytes: bool = False,
    mime: str | None = None,
    filename: str | None = None,
) -> BeaconTaskResponse:
    rec = registry.create(action, implant_id, "beacon")
    import asyncio

    async def runner() -> None:
        try:
            bcn = await hub.client.interact_beacon(implant_id)
            # InteractiveBeacon's commands are wrapped with @beacon_taskresult:
            # they queue the task and return an asyncio.Future that resolves
            # when the beacon checks in and the server pushes its result back.
            queued = await call(bcn)
            # The decorator stored (Future, pb_object) by Sliver-side TaskID;
            # match by Future identity to recover the TaskID for the SentAt
            # watcher below.
            sliver_tid: str | None = None
            try:
                for k, (fut, _) in getattr(bcn, "beacon_tasks", {}).items():
                    if fut is queued:
                        sliver_tid = k
                        break
            except Exception:  # noqa: BLE001 — defensive; sliver-py shape may shift
                sliver_tid = None
            watcher = asyncio.create_task(
                _watch_sent_to_beacon(rec.task_id, implant_id, sliver_tid, queued),
            ) if asyncio.isfuture(queued) else None
            try:
                raw = await queued if asyncio.isfuture(queued) else queued
            finally:
                if watcher and not watcher.done():
                    watcher.cancel()
            if as_bytes:
                payload_bytes = extract(raw)
                registry.set_complete(
                    rec.task_id, result={"size": len(payload_bytes), "filename": filename},
                    result_kind=result_kind,
                    result_bytes=payload_bytes,
                    result_mime=mime, result_filename=filename,
                )
            else:
                registry.set_complete(rec.task_id, result=extract(raw), result_kind=result_kind)
        except Exception as e:  # noqa: BLE001
            log.warning("beacon task %s/%s failed: %s", implant_id, action, e)
            registry.set_error(rec.task_id, e)

    asyncio.create_task(runner())
    return BeaconTaskResponse(task_id=rec.task_id, queued_at=rec.queued_at)


# ── exec ───────────────────────────────────────────────────────────

@router.post("/{implant_id}/exec")
async def exec_implant(implant_id: str, req: ImplantExecRequest):
    if not req.argv:
        raise HTTPException(status_code=400, detail="argv must be non-empty")
    kind, _info = await _resolve(implant_id)
    head, args = req.argv[0], req.argv[1:]
    if kind == "session":
        t0 = time.perf_counter()
        try:
            iact = await hub.client.interact_session(implant_id)
            result = await iact.execute(head, args, output=True)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"exec failed: {e}")
        d = _exec_result_dict(result)
        return SessionExecResponse(
            stdout=d["stdout"], stderr=d["stderr"], exit_code=d["exit_code"],
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
    return await _run_beacon_task(
        implant_id, "exec",
        lambda b: b.execute(head, args, output=True),
        _exec_result_dict, "exec",
    )


# ── ls ─────────────────────────────────────────────────────────────

@router.post("/{implant_id}/ls")
async def ls_implant(implant_id: str, req: ImplantLsRequest):
    kind, _info = await _resolve(implant_id)
    if kind == "session":
        try:
            iact = await hub.client.interact_session(implant_id)
            result = await iact.ls(req.path)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"ls failed: {e}")
        return {"kind": "session", **_ls_result_dict(result)}
    return await _run_beacon_task(
        implant_id, "ls",
        lambda b: b.ls(req.path), _ls_result_dict, "ls",
    )


# ── ps ─────────────────────────────────────────────────────────────

async def _ps_via_beacon(bcn):
    """sliver-py 0.0.19's InteractiveBeacon.ps() is broken: its base
    BaseInteractiveCommands.ps() returns ``list(processes.Processes)``, so the
    ``@beacon_taskresult`` wrapper then does ``task_response.Response.TaskID``
    on a *list* → ``'list' object has no attribute 'Response'``. ps is the
    only command whose base impl post-processes into a list, so it's the only
    one that trips this.

    We invoke the Ps RPC manually (mirroring _open_session_via_beacon) and
    register the Future ourselves keyed by the real Sliver TaskID. The SDK's
    taskresult-events listener then resolves it with a parsed Ps proto (which
    carries .Processes), and the rest of _run_beacon_task works unchanged."""
    import asyncio
    if _sliver_pb2 is None:
        raise RuntimeError("sliver_pb2 unavailable; cannot construct PsReq")
    pb = _sliver_pb2.PsReq()
    task_response = await bcn._stub.Ps(bcn._request(pb), timeout=bcn.timeout)
    fut: asyncio.Future = asyncio.Future()
    bcn.beacon_tasks[task_response.Response.TaskID] = (fut, _sliver_pb2.Ps)
    return fut


@router.post("/{implant_id}/ps")
async def ps_implant(implant_id: str):
    kind, _info = await _resolve(implant_id)
    if kind == "session":
        try:
            iact = await hub.client.interact_session(implant_id)
            result = await iact.ps()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"ps failed: {e}")
        return {"kind": "session", **_ps_result_dict(result)}
    return await _run_beacon_task(
        implant_id, "ps",
        _ps_via_beacon, _ps_result_dict, "ps",
    )


# ── screenshot ─────────────────────────────────────────────────────

@router.post("/{implant_id}/screenshot", response_model=TaskQueuedResponse)
async def screenshot_implant(implant_id: str):
    """Always async — even sessions may need a window/desktop round-trip we
    don't want to block the request loop on. Streamed via /tasks/{id}/result."""
    kind, _info = await _resolve(implant_id)
    if kind == "session":
        # Sessions can still do this synchronously; reuse the runner so the
        # frontend has a single code path (task_id → poll/WS).
        return await _run_session_as_task(
            implant_id, "screenshot",
            lambda iact: iact.screenshot(),
            _screenshot_bytes, "screenshot",
            as_bytes=True, mime="image/png", filename=f"screenshot-{implant_id}.png",
        )
    return await _run_beacon_task(
        implant_id, "screenshot",
        lambda b: b.screenshot(), _screenshot_bytes, "screenshot",
        as_bytes=True, mime="image/png", filename=f"screenshot-{implant_id}.png",
    )


# ── download ───────────────────────────────────────────────────────

@router.post("/{implant_id}/download", response_model=TaskQueuedResponse)
async def download_implant(implant_id: str, req: ImplantPathRequest):
    kind, _info = await _resolve(implant_id)
    if kind == "session":
        return await _run_session_as_task(
            implant_id, "download",
            lambda iact: iact.download(req.path), _download_bytes, "download",
            as_bytes=True, mime="application/octet-stream",
            filename=req.path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "download.bin",
        )
    return await _run_beacon_task(
        implant_id, "download",
        lambda b: b.download(req.path), _download_bytes, "download",
        as_bytes=True, mime="application/octet-stream",
        filename=req.path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "download.bin",
    )


# ── kill ───────────────────────────────────────────────────────────

@router.post("/{implant_id}/kill")
async def kill_implant(implant_id: str):
    kind, _info = await _resolve(implant_id)
    if kind == "session":
        try:
            iact = await hub.client.interact_session(implant_id)
            await iact.kill()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"kill failed: {e}")
        return {"kind": "session", "ok": True}
    return await _run_beacon_task(
        implant_id, "kill",
        lambda b: b.kill(), lambda _r: {"ok": True}, "kill",
    )


# ── Session-as-task runner (shared with beacon path) ───────────────

async def _run_session_as_task(
    implant_id: str, action: str, call, extract, result_kind: str,
    *, as_bytes: bool = False, mime: str | None = None, filename: str | None = None,
) -> TaskQueuedResponse:
    rec = registry.create(action, implant_id, "session")
    import asyncio

    async def runner() -> None:
        try:
            registry.set_running(rec.task_id)
            iact = await hub.client.interact_session(implant_id)
            raw = await call(iact)
            if as_bytes:
                payload_bytes = extract(raw)
                registry.set_complete(
                    rec.task_id, result={"size": len(payload_bytes), "filename": filename},
                    result_kind=result_kind,
                    result_bytes=payload_bytes,
                    result_mime=mime, result_filename=filename,
                )
            else:
                registry.set_complete(rec.task_id, result=extract(raw), result_kind=result_kind)
        except Exception as e:  # noqa: BLE001
            log.warning("session-as-task %s/%s failed: %s", implant_id, action, e)
            registry.set_error(rec.task_id, e)

    asyncio.create_task(runner())
    return TaskQueuedResponse(kind="session", task_id=rec.task_id, queued_at=rec.queued_at)


# ── interactive (beacon → session promotion) ───────────────────────

async def _open_session_via_beacon(bcn, c2s: list[str], delay: int = 0):
    """sliver-py 0.0.19's InteractiveBeacon.interactive_session() is an empty
    stub. We invoke the gRPC OpenSession RPC manually and then register a
    Future in the InteractiveBeacon's beacon_tasks dict — the SDK's existing
    taskresult-events listener will complete that Future when the beacon's
    OpenSession ack comes back, so the rest of _run_beacon_task (await on
    Future + watcher for set_running) keeps working unchanged."""
    import asyncio
    if _sliver_pb2 is None:
        raise RuntimeError("sliver_pb2 unavailable; cannot construct OpenSession")
    pb = _sliver_pb2.OpenSession(C2s=c2s, Delay=delay)
    task_response = await bcn._stub.OpenSession(bcn._request(pb), timeout=bcn.timeout)
    fut: asyncio.Future = asyncio.Future()
    bcn.beacon_tasks[task_response.Response.TaskID] = (fut, _sliver_pb2.OpenSession)
    return fut


def _derive_c2_for_promotion(beacon_info: dict[str, Any]) -> list[str]:
    """Best-effort C2 URL list for OpenSession. We pass the beacon's existing
    `active_c2` if known, else an empty list — sliver-server's OpenSession
    handler falls back to the beacon's baked-in config when C2s is empty."""
    active = str(beacon_info.get("active_c2") or "").strip()
    return [active] if active else []


def _extract_open_session(result: Any) -> dict[str, Any]:
    """The future resolves to an OpenSession proto echoing the Request/Response
    envelope. There's no rich payload — surface the Response.Err (if any) for
    the operator's log line."""
    err = ""
    try:
        err = (getattr(getattr(result, "Response", None), "Err", "") or "")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": not err, "err": err}


# ── upload ─────────────────────────────────────────────────────────

_UPLOAD_MAX_BYTES = 100 * 1024 * 1024  # 100 MB


def _is_absolute_path(p: str) -> bool:
    """Accept POSIX absolute (`/...`) and Windows absolute (`C:\\...`,
    `C:/...`, or UNC `\\\\host\\share`). We deliberately don't normalize
    backslashes — the operator passes the path verbatim to the target."""
    if not p:
        return False
    if p.startswith("/"):
        return True
    if p.startswith("\\\\"):
        return True
    if len(p) >= 3 and p[0].isalpha() and p[1] == ":" and p[2] in ("\\", "/"):
        return True
    return False


@router.post("/{implant_id}/upload")
async def upload_to_implant(
    implant_id: str,
    file: UploadFile = File(...),
    dest_path: str = Form(default=""),
):
    # Default "" so a missing/empty dest_path lands in our explicit 400 path
    # rather than FastAPI's 422 form-validation response.
    if not dest_path:
        raise HTTPException(status_code=400, detail="dest_path is required")
    if not _is_absolute_path(dest_path):
        raise HTTPException(status_code=400, detail="dest_path must be absolute")
    # Resolve implant FIRST so a 404 short-circuits before we read the body.
    kind, _info = await _resolve(implant_id)
    # Read with a hard byte cap; abort the moment we exceed it.
    data = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > _UPLOAD_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"file too large (limit {_UPLOAD_MAX_BYTES} bytes)",
            )
    payload = bytes(data)
    size = len(payload)

    if kind == "session":
        try:
            iact = await hub.client.interact_session(implant_id)
            await iact.upload(dest_path, payload)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"upload failed: {e}")
        return SessionUploadResponse(bytes_written=size, dest_path=dest_path)

    # Beacon: async — queue the task. The extract closure captures size +
    # dest so the result line ("uploaded N bytes to <path>") can render
    # without parsing the Upload proto (which doesn't carry BytesWritten).
    def _extract(_raw: Any) -> dict[str, Any]:
        return {"bytes_written": size, "dest_path": dest_path}

    return await _run_beacon_task(
        implant_id, "upload",
        lambda b: b.upload(dest_path, payload),
        _extract, "upload",
    )


@router.post("/{implant_id}/interactive", response_model=BeaconTaskResponse)
async def promote_to_session(implant_id: str):
    """Promote a beacon to an interactive session via Sliver's OpenSession
    RPC. Returns BeaconTaskResponse — the task completes on next beacon
    check-in; the new session registers via the standard session-connected
    event (graph_dirty propagates to the frontend)."""
    kind, info = await _resolve(implant_id)
    if kind == "session":
        raise HTTPException(
            status_code=400,
            detail="already interactive; id resolves to a session",
        )
    c2s = _derive_c2_for_promotion(info)
    return await _run_beacon_task(
        implant_id, "interactive",
        lambda b: _open_session_via_beacon(b, c2s, 0),
        _extract_open_session, "interactive",
    )
