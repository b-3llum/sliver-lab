"""Read-only tail of sliver-server's audit log.

sliver appends one JSON object per line to ~/.sliver/logs/audit.json:

    {"level":"info","msg":"{\\"request\\":\\"{}\\",\\"method\\":\\"/rpcpb.SliverRPC/GetSessions\\",
      \\"remote_ip\\":\\"127.0.0.1:42544\\",\\"user\\":\\"bellum\\"}","time":"2026-05-30T02:08:17-04:00"}

The real payload is a JSON string nested under `msg`. We promote
user→operator, method→action, and keep the rest under `details`. There's no
explicit "target" field in this schema, so it's left empty unless the nested
payload carries one.

The file can grow large, so we read it backward in blocks (newest-first) and
stop as soon as we have `limit` rows or cross the `since` boundary — never
loading the whole file into memory.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Query

from config import AUDIT_LOG_PATH, audit_polling_actions
from models import AuditEntry, AuditResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])

# Filtering trims most lines, so allow a deeper scan than the old 1000.
_MAX_LIMIT = 5000


def _action_tail(action: str) -> str:
    """Trailing gRPC method name, e.g. /rpcpb.SliverRPC/GetSessions → GetSessions."""
    return action.rsplit("/", 1)[-1] if action else action


def _parse_iso(s: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp; naive values are treated as UTC so all
    comparisons are between tz-aware datetimes."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iter_lines_reverse(path: Path, block_size: int = 8192) -> Iterator[str]:
    """Yield complete lines newest-first, reading the file backward in blocks."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        tail = b""
        while pos > 0:
            read = min(block_size, pos)
            pos -= read
            f.seek(pos)
            tail = f.read(read) + tail
            parts = tail.split(b"\n")
            tail = parts[0]  # leading partial — earlier block(s) complete it
            for ln in reversed(parts[1:]):
                if ln:
                    yield ln.decode("utf-8", "replace")
        if tail:
            yield tail.decode("utf-8", "replace")


def _parse_entry(line: str) -> AuditEntry | None:
    """Normalize one raw audit line. Returns None for malformed lines."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None

    inner: dict[str, Any] = {}
    msg = obj.get("msg")
    if isinstance(msg, str):
        try:
            decoded = json.loads(msg)
            inner = decoded if isinstance(decoded, dict) else {"msg": msg}
        except json.JSONDecodeError:
            inner = {"msg": msg}
    elif isinstance(msg, dict):
        inner = msg

    operator = inner.get("user") or inner.get("operator") or obj.get("user") or ""
    action = inner.get("method") or inner.get("action") or ""
    target = inner.get("target") or inner.get("session") or inner.get("beacon") or ""

    # Everything not promoted to a column goes into the collapsible details.
    details = {k: v for k, v in inner.items() if k not in ("user", "method")}
    if obj.get("level"):
        details.setdefault("level", obj["level"])

    return AuditEntry(
        timestamp=str(obj.get("time") or obj.get("timestamp") or ""),
        operator=str(operator),
        action=str(action),
        target=str(target),
        details=details,
    )


def scan_entries(
    path: Path,
    *,
    since: str | None = None,
    include_polling: bool = False,
    limit: int = _MAX_LIMIT,
) -> tuple[list[AuditEntry], int]:
    """Scan the audit log newest-first, applying the `since` boundary and the
    polling-action filter. Returns (entries_newest_first, malformed_count).

    Shared by the /api/audit tail and the engagement-report builder so the
    parsing + filtering rules stay in one place. Raises OSError on read
    failure; callers translate that to an HTTP error as appropriate.
    """
    since_dt = _parse_iso(since)
    # Routine poll RPCs are dropped unless the caller asks to see them.
    polling = set() if include_polling else audit_polling_actions()
    entries: list[AuditEntry] = []
    malformed = 0
    for line in _iter_lines_reverse(path):
        entry = _parse_entry(line)
        if entry is None:
            malformed += 1
            continue
        if since_dt is not None:
            ts = _parse_iso(entry.timestamp)
            # File is chronological; once we cross below `since`, everything
            # earlier is older too — stop scanning. (Checked before the
            # polling filter so the boundary still terminates the scan.)
            if ts is not None and ts < since_dt:
                break
        if polling and _action_tail(entry.action) in polling:
            continue
        entries.append(entry)
        if len(entries) >= limit:
            break
    return entries, malformed


@router.get("", response_model=AuditResponse)
async def get_audit(
    limit: int = Query(default=200),
    since: str | None = Query(default=None),
    include_polling: bool = Query(default=False),
) -> AuditResponse:
    limit = max(1, min(limit, _MAX_LIMIT))
    path = AUDIT_LOG_PATH
    if not path.is_file():
        # sliver-server may not be configured to write an audit log.
        return AuditResponse(entries=[])

    try:
        entries, malformed = scan_entries(
            path, since=since, include_polling=include_polling, limit=limit,
        )
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"audit read failed: {e}")

    if malformed:
        log.warning("skipped %d malformed audit line(s)", malformed)
    return AuditResponse(entries=entries)
