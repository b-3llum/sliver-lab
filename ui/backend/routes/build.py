"""Implant build endpoint — proxies the form to avgen.py.

GET  /api/build/options  → introspects avgen.py's argparse and returns a
                           grouped, UI-renderable schema.
POST /api/build          → subprocess-runs avgen.py with the chosen flags,
                           returns the built binary as application/octet-stream.

avgen.py path is configurable via AVGEN_PATH env var (defaults to
/home/bellum/tools/avgen.py). The build cwd is a per-request tempdir under
AVGEN_BUILD_DIR; nothing is persisted on the BFF side.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import shlex
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config import AVGEN_BUILD_DIR, AVGEN_PATH, AVGEN_PYTHON, AVGEN_TIMEOUT
from models import BuildField, BuildGroup, BuildRequest, BuildSchema

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/build", tags=["build"])


# ── Curated grouping & flag policy ─────────────────────────────────────
# Order matters — groups render top-to-bottom in the form. Any avgen flag
# not listed here is silently hidden from the UI (typically dev/AI flags).

_GROUP_ORDER: list[tuple[str, str | None, bool, list[str]]] = [
    # (group_name, description, exclusive, [dest, ...])
    ("Target", "Required: where the implant calls home.", False,
        ["lhost", "lport", "target", "arch"]),
    ("Payload source", "Pick exactly one. msfvenom (default) | raw shellcode "
                       "| arbitrary PE via donut | mimikatz preset.", True,
        ["payload", "payload_file", "payload_donut", "mimikatz_path"]),
    ("Payload options", "msfvenom transport + stager knobs.", False,
        ["proto", "stageless", "retry_attempts", "retry_delay"]),
    ("Donut wrap", "(--payload-donut) PIC-wrap a PE/.NET assembly.", False,
        ["donut_arch", "donut_bypass", "donut_compress", "donut_entropy"]),
    ("Mimikatz", "(--mimikatz-path) PE pre-processing + delivery format.", False,
        ["mimikatz_format", "mimikatz_cmd", "mimikatz_strip"]),
    ("Output", "Loader format and on-disk layout.", False,
        ["format", "exec_mode", "callback", "target_proc", "target_proc_pool"]),
    ("Crypto", "Encryption + per-build polymorphism.", False,
        ["enc", "keystone_prefix", "split_shellcode", "pad_to", "version_info"]),
    ("Evasion", "AMSI/ETW/sleep/anti-VM controls.", False,
        ["sleep", "patch_amsi", "patch_etw", "unhook_ntdll",
         "anti_vm", "anti_hypervisor"]),
    ("Hardening", "Hell's Gate, sleep masking, self-delete, PPID spoof.", False,
        ["hard", "sleep_mask", "self_delete", "ppid_spoof", "no_crt"]),
    ("Build", "Compile + output layout.", False,
        ["upx"]),
]

# Anything in the parser but NOT listed above is hidden by default.
_HIDDEN_DESTS = {
    "help",
    "seed",                  # deterministic-build flag; dev only
    "no_compile",            # UI always wants the binary; not the .c
    "keep_source",
    "output",                # we choose the output path
    "ai_explain_error",
    "ai_plan",
}


# Cache the parser so we don't reload avgen.py on every request.
_parser_cache: argparse.ArgumentParser | None = None


def _load_parser() -> argparse.ArgumentParser | None:
    """Dynamically import avgen.py and return its argparse parser. Cached."""
    global _parser_cache
    if _parser_cache is not None:
        return _parser_cache
    if not AVGEN_PATH.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("avgen_introspect", AVGEN_PATH)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        # Register in sys.modules BEFORE exec — dataclasses defined in the loaded
        # module need to look up the module by name during decoration; an
        # unregistered module crashes with NoneType.__dict__.
        import sys as _sys
        _sys.modules["avgen_introspect"] = mod
        spec.loader.exec_module(mod)
    except Exception as e:
        log.error("Failed to import avgen.py for introspection: %s", e)
        return None
    if not hasattr(mod, "build_parser"):
        log.error("avgen.py loaded but no build_parser() function found")
        return None
    _parser_cache = mod.build_parser()
    return _parser_cache


def _action_to_field(act: argparse.Action) -> BuildField | None:
    """Translate one argparse action into a UI field. Returns None to skip."""
    if act.dest in _HIDDEN_DESTS or act.dest == argparse.SUPPRESS:
        return None
    if not act.option_strings:
        return None  # positional; avgen has none, but defend anyway

    primary_flag = max(act.option_strings, key=len)  # prefer the long form

    # Determine kind from action class + type + choices.
    kind: str
    if isinstance(act, argparse._StoreTrueAction):
        kind = "bool"
    elif act.choices is not None:
        kind = "choice"
    elif act.type is int:
        kind = "int"
    else:
        kind = "string"

    choices = list(act.choices) if act.choices is not None else None
    if choices is not None:
        choices = [str(c) for c in choices]

    return BuildField(
        name=act.dest,
        flag=primary_flag,
        kind=kind,  # type: ignore[arg-type]
        default=act.default if act.default is not argparse.SUPPRESS else None,
        required=getattr(act, "required", False),
        choices=choices,
        metavar=act.metavar if isinstance(act.metavar, str) else None,
        help=(act.help or "").replace("(default: %(default)s)", "").strip(),
    )


def _build_schema() -> BuildSchema:
    parser = _load_parser()
    present = parser is not None
    groups: list[BuildGroup] = []

    if parser is None:
        return BuildSchema(avgen_path=str(AVGEN_PATH), avgen_present=False, groups=[])

    # Index actions by dest for the group walker.
    by_dest: dict[str, argparse.Action] = {
        a.dest: a for a in parser._actions if a.dest and a.dest != "help"
    }

    for name, desc, exclusive, dests in _GROUP_ORDER:
        fields: list[BuildField] = []
        for d in dests:
            act = by_dest.get(d)
            if act is None:
                continue  # silently skip — avgen renamed the flag
            f = _action_to_field(act)
            if f:
                fields.append(f)
        if fields:
            groups.append(BuildGroup(
                name=name, description=desc, exclusive=exclusive, fields=fields,
            ))

    return BuildSchema(
        avgen_path=str(AVGEN_PATH),
        avgen_present=present,
        groups=groups,
    )


def _options_to_args(opts: dict[str, Any]) -> list[str]:
    """Translate {dest: value} → CLI args, respecting types."""
    parser = _load_parser()
    if parser is None:
        raise HTTPException(status_code=503, detail=f"avgen.py not loadable at {AVGEN_PATH}")
    by_dest: dict[str, argparse.Action] = {
        a.dest: a for a in parser._actions if a.dest
    }

    args: list[str] = []
    for dest, value in opts.items():
        if dest in _HIDDEN_DESTS:
            continue
        act = by_dest.get(dest)
        if act is None or not act.option_strings:
            continue
        flag = max(act.option_strings, key=len)

        # Skip empties / Nones unless required.
        if value in (None, "", []):
            continue

        if isinstance(act, argparse._StoreTrueAction):
            if bool(value):
                args.append(flag)
        else:
            args.extend([flag, str(value)])
    return args


def _guess_output_filename(opts: dict[str, Any], build_dir: Path) -> tuple[Path, str]:
    """Decide where avgen will drop its artifact + what to name the download."""
    target = opts.get("target", "win")
    fmt = opts.get("format", "exe")
    mk_format = opts.get("mimikatz_format")

    if opts.get("mimikatz_path"):
        if mk_format == "ps1":
            name = "impl.ps1"
        elif mk_format == "bof":
            name = "mimikatz.bof.txt"
        else:
            name = "impl.exe"
    elif target == "linux":
        name = "impl.elf"
    elif fmt == "dll":
        name = "impl.dll"
    elif fmt == "cs":
        name = "impl.exe"  # csharp compile output
    else:
        name = "impl.exe"

    return build_dir / name, name


# ── routes ─────────────────────────────────────────────────────────────


@router.get("/options", response_model=BuildSchema)
async def get_build_options() -> BuildSchema:
    return _build_schema()


@router.post("")
async def build_implant(req: BuildRequest):
    if not AVGEN_PATH.is_file():
        raise HTTPException(status_code=503, detail=f"avgen.py not found at {AVGEN_PATH}")

    AVGEN_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    build_dir = Path(tempfile.mkdtemp(prefix="build-", dir=str(AVGEN_BUILD_DIR)))
    out_path, filename = _guess_output_filename(req.options, build_dir)

    args = _options_to_args(req.options)
    args.extend(["-o", str(out_path)])

    cmd = [AVGEN_PYTHON, str(AVGEN_PATH), *args]
    log.info("avgen build: %s", shlex.join(cmd))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(build_dir),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to spawn avgen: {e}")

    try:
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=AVGEN_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(
            status_code=504,
            detail=f"avgen exceeded {AVGEN_TIMEOUT}s timeout — check "
                   f"--retry-attempts / large --pad-to / mingw stalls",
        )

    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace")[-2000:]
        log.warning("avgen exit %s: %s", proc.returncode, err)
        raise HTTPException(
            status_code=422,
            detail=f"avgen failed (exit {proc.returncode}):\n{err}",
        )

    if not out_path.is_file():
        # avgen exited 0 but the expected output isn't there — pick first impl.*
        candidates = sorted(build_dir.glob("impl.*"))
        if candidates:
            out_path = candidates[0]
            filename = out_path.name
        else:
            raise HTTPException(
                status_code=500,
                detail=f"avgen returned 0 but no output at {out_path}. "
                       f"build dir: {build_dir}",
            )

    media_type = (
        "text/plain" if filename.endswith(".txt")
        else "text/x-powershell" if filename.endswith(".ps1")
        else "application/octet-stream"
    )
    return FileResponse(
        str(out_path),
        media_type=media_type,
        filename=filename,
        headers={"X-Avgen-Cmd": shlex.join(cmd)[:1024]},
    )
