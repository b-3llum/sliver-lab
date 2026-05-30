"""Beacon listing + pending task queue inspection + cleanup."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException

from models import BeaconInfo
from sliver_client import _pb_to_dict, hub

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/beacons", tags=["beacons"])


def _is_stale_beacon(interval_ns: int, next_checkin: int) -> bool:
    """Overdue by more than 2× the check-in interval. Mirrors the graph's
    isLateBeacon: interval is nanoseconds, next_checkin is unix seconds."""
    if interval_ns <= 0 or next_checkin <= 0:
        return False
    return (time.time() - next_checkin) > 2 * (interval_ns / 1e9)


def _beacon_to_model(b) -> BeaconInfo:
    d = _pb_to_dict(b) or {}
    interval = int(d.get("Interval") or d.get("interval") or 0)
    next_checkin = int(d.get("NextCheckin") or d.get("next_checkin") or 0)
    return BeaconInfo(
        ID=str(d.get("ID") or d.get("id") or ""),
        name=d.get("Name") or d.get("name", ""),
        hostname=d.get("Hostname") or d.get("hostname", ""),
        username=d.get("Username") or d.get("username", ""),
        os=d.get("OS") or d.get("os", ""),
        arch=d.get("Arch") or d.get("arch", ""),
        transport=d.get("Transport") or d.get("transport", ""),
        remote_address=d.get("RemoteAddress") or d.get("remote_address", ""),
        pid=int(d.get("PID") or d.get("pid") or 0),
        next_checkin=next_checkin,
        interval=interval,
        jitter=int(d.get("Jitter") or d.get("jitter") or 0),
        tasks_count=int(d.get("TasksCount") or d.get("tasks_count") or 0),
        tasks_count_completed=int(d.get("TasksCountCompleted") or d.get("tasks_count_completed") or 0),
        stale=_is_stale_beacon(interval, next_checkin),
    )


@router.get("", response_model=list[BeaconInfo])
async def list_beacons() -> list[BeaconInfo]:
    try:
        beacons = await hub.client.beacons()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return [_beacon_to_model(b) for b in beacons]


@router.get("/{beacon_id}/tasks")
async def list_tasks(beacon_id: str) -> list[dict]:
    try:
        tasks = await hub.client.beacon_tasks(beacon_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AttributeError:
        # older sliver-py — fall back to empty
        return []
    return [_pb_to_dict(t) or {} for t in tasks]


# ── Forget (remove) beacon rows ────────────────────────────────────
#
# sliver-server keeps beacon rows after the implant exits/crashes. sliver-py
# exposes removal via kill_beacon(), which issues the RmBeacon RPC. There is
# no separate rm_beacon method in 0.0.19 — kill_beacon *is* the row delete.

# NOTE: DELETE /stale must be declared before DELETE /{beacon_id}; otherwise
# the path-param route matches the literal "stale" as a beacon id (str params
# don't 422) and the bulk handler is never reached.
@router.delete("/stale")
async def delete_stale_beacons() -> dict:
    """Remove every beacon whose next check-in is overdue by >2× its interval."""
    try:
        beacons = await hub.client.beacons()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    deleted = 0
    for b in beacons:
        m = _beacon_to_model(b)
        if not m.stale:
            continue
        try:
            await hub.client.kill_beacon(m.id)
            deleted += 1
        except Exception as e:  # noqa: BLE001 — best effort; keep going
            log.warning("kill_beacon(%s) failed during stale sweep: %s", m.id, e)
    log.info("stale beacon sweep: removed %d", deleted)
    return {"deleted_count": deleted}


@router.delete("/{beacon_id}")
async def delete_beacon(beacon_id: str) -> dict:
    try:
        beacons = await hub.client.beacons()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    known = {str(getattr(b, "ID", None) or getattr(b, "id", None) or "") for b in beacons}
    if beacon_id not in known:
        raise HTTPException(status_code=404, detail=f"no beacon with id {beacon_id}")
    try:
        await hub.client.kill_beacon(beacon_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"kill_beacon failed: {e}")
    log.info("forget beacon id=%s", beacon_id)
    return {"ok": True}
