"""BOF (Beacon Object File) library — directory scan + Sliver command builder.

Operator drops .o files into $BOF_DIR (default ~/.sliver/bofs). Optional
category subdirectories group entries in the UI. Nothing is bundled.

Layout examples:

    ~/.sliver/bofs/
    ├── credential-access/
    │   ├── mimikatz.x64.o
    │   └── tgtdeleg.x64.o
    ├── discovery/
    │   └── netuser.x64.o
    └── notes.o         # ungrouped → category "uncategorized"
"""
from __future__ import annotations

import shlex
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config import bof_dir
from models import BofEntry, BofLibrary, BofRunCommand

router = APIRouter(prefix="/api/bofs", tags=["bofs"])

_BOF_SUFFIXES = (".o", ".obj")
_UNCATEGORIZED = "uncategorized"


def _scan_bofs(root: Path) -> list[BofEntry]:
    if not root.is_dir():
        return []
    entries: list[BofEntry] = []
    seen: set[str] = set()  # de-dupe by name
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _BOF_SUFFIXES:
            continue
        rel_parent = path.parent.relative_to(root)
        category = str(rel_parent) if str(rel_parent) != "." else _UNCATEGORIZED
        name = path.stem  # filename minus suffix
        if name in seen:
            # If the same name appears in two dirs, suffix with the category
            # so the UI shows both rather than dropping one silently.
            name = f"{name}@{category}"
        seen.add(name)
        entries.append(BofEntry(
            name=name,
            category=category,
            path=str(path),
            available=True,
        ))
    return entries


@router.get("/library", response_model=BofLibrary)
async def library_info() -> BofLibrary:
    root, env_set = bof_dir()
    exists = root.is_dir()
    count = len(_scan_bofs(root)) if exists else 0
    return BofLibrary(dir=str(root), env_set=env_set, exists=exists, count=count)


@router.get("", response_model=list[BofEntry])
async def list_bofs() -> list[BofEntry]:
    root, _ = bof_dir()
    return _scan_bofs(root)


@router.get("/{name}", response_model=BofEntry)
async def get_bof(name: str) -> BofEntry:
    root, _ = bof_dir()
    for e in _scan_bofs(root):
        if e.name == name:
            return e
    raise HTTPException(status_code=404, detail=f"BOF {name!r} not on disk under {root}")


@router.post("/{name}/build_command", response_model=BofRunCommand)
async def build_command(name: str, session_id: str, args: list[str] | None = None) -> BofRunCommand:
    """Emit the Sliver console command to run this BOF against a session.

    Direct execution from the BFF requires Sliver's coff-loader extension to
    be registered against the implant. Until that's wired, we just emit the
    `inline-execute` line the operator pastes into their sliver-client shell.
    """
    root, _ = bof_dir()
    entry = next((e for e in _scan_bofs(root) if e.name == name), None)
    if entry is None or not entry.path:
        raise HTTPException(
            status_code=404,
            detail=f"BOF {name!r} not on disk under {root}",
        )

    use_line = f"use {shlex.quote(session_id)}"
    exec_parts = ["inline-execute", entry.path, *(args or [])]
    exec_line = " ".join(shlex.quote(p) for p in exec_parts)
    cmd = f"{use_line}\n{exec_line}"
    note = (
        "Paste into your sliver-client console. Requires the `coff-loader` "
        "extension (install via `armory install coff-loader` on the server)."
    )
    return BofRunCommand(name=name, session_id=session_id, sliver_command=cmd, note=note)
