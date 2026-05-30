"""In-process task registry for async beacon operations.

A POST to /api/implants/{id}/* with a beacon target queues the work into an
asyncio.Task and returns a task_id immediately. The runner stores result +
state here; when the underlying sliver-py call resolves (next beacon
check-in), the registry pushes a `task_update` envelope onto the Sliver
event bus so connected browsers can collapse the "queued" line into output.

Lifetime: process. Not persisted. If the BFF restarts mid-task, the
in-flight task is lost — that's the simplest semantic and matches the
brief's "orphaned task results get dropped" guidance.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from models import TaskStatus

log = logging.getLogger(__name__)

# Hard cap on records so a long-lived process doesn't grow unbounded.
_MAX_RECORDS = 2048


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _Record:
    task_id: str
    state: str
    kind: str
    implant_id: str
    implant_kind: str
    queued_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result_kind: Optional[str] = None
    result: Any = None
    result_bytes: Optional[bytes] = None
    result_mime: Optional[str] = None     # for /result endpoint
    result_filename: Optional[str] = None
    error: Optional[str] = None
    fut: Optional[asyncio.Task] = field(default=None, repr=False)


class TaskRegistry:
    def __init__(self) -> None:
        self._records: dict[str, _Record] = {}
        self._order: list[str] = []
        # Broadcaster injected at app startup so tests don't need a live hub.
        self._broadcast = None  # type: ignore[var-annotated]

    def set_broadcaster(self, fn) -> None:
        """Inject the async fn(payload: dict) used to push task_update events."""
        self._broadcast = fn

    def create(self, kind: str, implant_id: str, implant_kind: str) -> _Record:
        tid = str(uuid.uuid4())
        rec = _Record(
            task_id=tid, state="queued", kind=kind,
            implant_id=implant_id, implant_kind=implant_kind,
            queued_at=_now_iso(),
        )
        self._records[tid] = rec
        self._order.append(tid)
        # Trim from the front if we exceed the cap.
        while len(self._order) > _MAX_RECORDS:
            old = self._order.pop(0)
            self._records.pop(old, None)
        return rec

    def get(self, task_id: str) -> _Record | None:
        return self._records.get(task_id)

    def status(self, task_id: str) -> TaskStatus | None:
        rec = self.get(task_id)
        if rec is None:
            return None
        return TaskStatus(
            task_id=rec.task_id, state=rec.state, kind=rec.kind,  # type: ignore[arg-type]
            implant_id=rec.implant_id, implant_kind=rec.implant_kind,
            queued_at=rec.queued_at, started_at=rec.started_at,
            completed_at=rec.completed_at,
            result_kind=rec.result_kind,  # type: ignore[arg-type]
            result=rec.result, error=rec.error,
        )

    def set_running(self, task_id: str) -> None:
        rec = self._records.get(task_id)
        if rec is None:
            return
        rec.state = "running"
        rec.started_at = _now_iso()
        self._schedule_emit(task_id, "running")

    def set_complete(
        self, task_id: str, result: Any,
        result_kind: str = "text",
        result_bytes: bytes | None = None,
        result_mime: str | None = None,
        result_filename: str | None = None,
    ) -> None:
        rec = self._records.get(task_id)
        if rec is None:
            return
        rec.state = "complete"
        rec.completed_at = _now_iso()
        rec.result_kind = result_kind
        rec.result = result
        rec.result_bytes = result_bytes
        rec.result_mime = result_mime
        rec.result_filename = result_filename
        self._schedule_emit(task_id, "complete")

    def set_error(self, task_id: str, err: BaseException | str) -> None:
        rec = self._records.get(task_id)
        if rec is None:
            return
        rec.state = "error"
        rec.completed_at = _now_iso()
        rec.error = str(err)
        self._schedule_emit(task_id, "error")

    def _schedule_emit(self, task_id: str, state: str) -> None:
        """Best-effort: only fire the broadcast if we're inside a running
        event loop. Sync test code that pokes the registry directly skips it."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        asyncio.create_task(self._emit(task_id, state))

    async def _emit(self, task_id: str, state: str) -> None:
        if self._broadcast is None:
            return
        try:
            await self._broadcast({"type": "task_update", "task_id": task_id, "state": state})
        except Exception as e:  # noqa: BLE001
            log.warning("task_update broadcast failed: %s", e)


# Singleton — imported by routes/implants.py and routes/tasks.py.
registry = TaskRegistry()
