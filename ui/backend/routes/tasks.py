"""Task lookup + binary result streaming for async implant operations."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from models import TaskStatus
from task_registry import registry

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskStatus)
async def get_task(task_id: str) -> TaskStatus:
    status = registry.status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"no task with id {task_id}")
    return status


@router.get("/{task_id}/result")
async def get_task_result(task_id: str):
    rec = registry.get(task_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"no task with id {task_id}")
    if rec.state != "complete":
        raise HTTPException(status_code=409, detail=f"task is {rec.state}, not complete")
    if rec.result_bytes is None:
        raise HTTPException(status_code=404, detail="this task has no file-typed result")
    headers = {}
    if rec.result_filename:
        headers["Content-Disposition"] = f'inline; filename="{rec.result_filename}"'
    return Response(
        content=rec.result_bytes,
        media_type=rec.result_mime or "application/octet-stream",
        headers=headers,
    )
