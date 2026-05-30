"""All active jobs (listeners are a subset)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models import JobInfo
from routes.listeners import _job_to_model
from sliver_client import hub

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobInfo])
async def list_jobs() -> list[JobInfo]:
    try:
        jobs = await hub.client.jobs()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return [_job_to_model(j) for j in jobs]


@router.delete("/{job_id}")
async def kill_job(job_id: int) -> dict:
    try:
        await hub.client.kill_job(job_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"kill_job failed: {e}")
    return {"ok": True, "id": job_id}
