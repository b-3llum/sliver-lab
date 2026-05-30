"""In-process registry of long-lived sliver-client subprocesses, one per
operator-side tunnel.

Sliver's tunneling primitives (portfwd / rportfwd / socks5) are implemented
in the *client* binary's Go code, not server-side, and sliver-py 0.0.19
exposes no wrappers. We drive them by spawning `sliver-client --rc <file>`
with a rc-script that selects the session and runs the tunnel command —
crucially WITHOUT `exit`, so the listener goroutine stays alive. The
subprocess sits at the prompt; SIGTERM tears it down cleanly.

Caveats:
  - Per-process cost: ~30 MB RSS per tunnel. Fine at operator scale.
  - State is in-memory; BFF restart loses the registry. A startup reaper
    SIGTERMs any leftover `sliver-client --rc` processes from previous
    runs so their listener sockets free up.
  - Output parsing for the success marker is regex-based against the
    ANSI-stripped first ~3 s of stdout.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

# How long to wait for the success marker after spawning.
_MARKER_TIMEOUT_S = 10.0
# How long to wait after SIGTERM before escalating to SIGKILL.
_TERM_GRACE_S = 3.0
# Bytes of subprocess output we keep around for diagnostics.
_OUTPUT_BUFFER_MAX = 8 * 1024

TunnelKind = Literal["portfwd", "rportfwd", "socks5"]

# Regexes match the ANSI-stripped success lines emitted by sliver-client
# v1.7.3 console. Captured per probe (Phase 5 discovery).
_MARKER_PATTERNS: dict[TunnelKind, re.Pattern[str]] = {
    "portfwd": re.compile(r"Port forwarding\s+\S+\s*->\s*\S+", re.IGNORECASE),
    "rportfwd": re.compile(r"Reverse port forwarding\s+\S+\s*<-\s*\S+", re.IGNORECASE),
    "socks5": re.compile(r"Started SOCKS5\s+\S+\s+\d+", re.IGNORECASE),
}

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _strip_ansi(s: str) -> str:
    return _ANSI.sub("", s)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Entry record ───────────────────────────────────────────────────


@dataclass
class TunnelEntry:
    id: str
    kind: TunnelKind
    session_id: str
    bind_addr: str
    bind_port: int
    remote_addr: str
    remote_port: int
    pid: int
    started_at: str
    rc_path: Path
    marker_seen: bool = False
    output_tail: bytearray = field(default_factory=bytearray)
    proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
    reader_task: asyncio.Task | None = field(default=None, repr=False)


# ── Registry ───────────────────────────────────────────────────────


class TunnelRegistry:
    def __init__(self) -> None:
        self._tunnels: dict[str, TunnelEntry] = {}
        self._lock = asyncio.Lock()

    # ── helpers ───────────────────────────────────────────────────

    @staticmethod
    def _build_rc_script(kind: TunnelKind, session_id: str, entry: TunnelEntry) -> str:
        """rc-script body — NO `exit`, so the listener goroutine stays alive."""
        use_line = f"use {session_id}\n"
        if kind == "portfwd":
            tunnel = (f"portfwd add --bind {entry.bind_addr}:{entry.bind_port} "
                      f"--remote {entry.remote_addr}:{entry.remote_port}\n")
        elif kind == "rportfwd":
            tunnel = (f"rportfwd add --bind {entry.bind_addr}:{entry.bind_port} "
                      f"--remote {entry.remote_addr}:{entry.remote_port}\n")
        elif kind == "socks5":
            tunnel = f"socks5 start --host {entry.bind_addr} --port {entry.bind_port}\n"
        else:
            raise ValueError(f"unknown kind: {kind}")
        return use_line + tunnel

    @staticmethod
    def _make_rc_file(content: str) -> Path:
        fd, path = tempfile.mkstemp(prefix="sliver-tunnel-rc-", suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(content)
        return Path(path)

    # ── public API ────────────────────────────────────────────────

    def list_for_session(self, session_id: str) -> list[TunnelEntry]:
        return [t for t in self._tunnels.values() if t.session_id == session_id]

    def get(self, tunnel_id: str) -> TunnelEntry | None:
        return self._tunnels.get(tunnel_id)

    def has_bind(self, session_id: str, bind_addr: str, bind_port: int) -> bool:
        return any(
            t.session_id == session_id
            and t.bind_addr == bind_addr
            and t.bind_port == bind_port
            for t in self._tunnels.values()
        )

    async def register(
        self,
        kind: TunnelKind,
        session_id: str,
        bind_addr: str,
        bind_port: int,
        remote_addr: str = "",
        remote_port: int = 0,
    ) -> TunnelEntry:
        """Spawn the subprocess, wait up to _MARKER_TIMEOUT_S for the success
        marker, then return the entry. Raises RuntimeError with the captured
        output if the marker doesn't appear; the subprocess gets SIGTERM'd
        as part of the failure path so we don't leak listeners."""
        async with self._lock:
            tid = str(uuid.uuid4())
            entry = TunnelEntry(
                id=tid, kind=kind, session_id=session_id,
                bind_addr=bind_addr, bind_port=bind_port,
                remote_addr=remote_addr, remote_port=remote_port,
                pid=0, started_at=_now_iso(), rc_path=Path(),
            )
            rc_text = self._build_rc_script(kind, session_id, entry)
            rc_path = self._make_rc_file(rc_text)
            entry.rc_path = rc_path

            try:
                proc = await asyncio.create_subprocess_exec(
                    "sliver-client", "--rc", str(rc_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    # New session so SIGTERM-the-group reliably kills the
                    # whole sliver-client tree even if it has children.
                    preexec_fn=os.setsid if sys.platform != "win32" else None,
                )
            except Exception as e:  # noqa: BLE001
                self._unlink_rc(entry.rc_path)
                raise RuntimeError(f"failed to spawn sliver-client: {e}") from e

            entry.proc = proc
            entry.pid = proc.pid or 0
            self._tunnels[tid] = entry

            pattern = _MARKER_PATTERNS[kind]
            entry.reader_task = asyncio.create_task(
                self._consume_output(entry, pattern),
            )

            # Wait for the marker to be seen (or for the proc to die early).
            try:
                await asyncio.wait_for(
                    self._wait_for_marker(entry), timeout=_MARKER_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                await self._cleanup(entry)
                raise RuntimeError(
                    f"sliver-client {kind} marker not seen within {_MARKER_TIMEOUT_S}s.\n"
                    f"last output:\n{_strip_ansi(bytes(entry.output_tail).decode('utf-8', 'replace'))[-2000:]}"
                )

            return entry

    async def close(self, tunnel_id: str) -> bool:
        """Stop the subprocess. Returns True if the tunnel was known."""
        async with self._lock:
            entry = self._tunnels.pop(tunnel_id, None)
            if entry is None:
                return False
        await self._cleanup(entry)
        return True

    async def close_all(self) -> None:
        async with self._lock:
            entries = list(self._tunnels.values())
            self._tunnels.clear()
        for e in entries:
            await self._cleanup(e)

    # ── internals ─────────────────────────────────────────────────

    async def _consume_output(
        self, entry: TunnelEntry, marker_pattern: re.Pattern[str],
    ) -> None:
        """Stream the subprocess stdout into output_tail, set marker_seen
        the first time we see the success regex on a stripped line."""
        proc = entry.proc
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    return
                entry.output_tail.extend(chunk)
                if len(entry.output_tail) > _OUTPUT_BUFFER_MAX:
                    del entry.output_tail[: len(entry.output_tail) - _OUTPUT_BUFFER_MAX]
                if not entry.marker_seen:
                    stripped = _strip_ansi(bytes(entry.output_tail).decode("utf-8", "replace"))
                    if marker_pattern.search(stripped):
                        entry.marker_seen = True
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("tunnel %s reader died: %s", entry.id, e)

    async def _wait_for_marker(self, entry: TunnelEntry) -> None:
        """Resolves when marker_seen flips True, OR raises if the
        subprocess dies before that."""
        proc = entry.proc
        assert proc is not None
        while not entry.marker_seen:
            if proc.returncode is not None:
                # Subprocess exited early — failure.
                raise RuntimeError(
                    f"sliver-client exited early (rc={proc.returncode}) before "
                    f"marker. output:\n"
                    f"{_strip_ansi(bytes(entry.output_tail).decode('utf-8', 'replace'))[-2000:]}"
                )
            await asyncio.sleep(0.05)

    async def _cleanup(self, entry: TunnelEntry) -> None:
        proc = entry.proc
        if proc is not None and proc.returncode is None:
            # Signal the whole process group; we put it in a new session
            # with os.setsid so SIGTERM-the-group reliably kills sliver-client
            # plus anything it spawned.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError) as e:
                log.warning("SIGTERM group %s failed: %s", entry.id, e)
            try:
                await asyncio.wait_for(proc.wait(), timeout=_TERM_GRACE_S)
            except asyncio.TimeoutError:
                log.warning("tunnel %s ignored SIGTERM — escalating to SIGKILL", entry.id)
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
        if entry.reader_task is not None and not entry.reader_task.done():
            entry.reader_task.cancel()
        self._unlink_rc(entry.rc_path)

    @staticmethod
    def _unlink_rc(rc_path: Path) -> None:
        try:
            if rc_path and rc_path.exists():
                rc_path.unlink()
        except OSError as e:
            log.warning("rc file unlink failed: %s", e)


# ── Orphan reaper (startup-only) ───────────────────────────────────


def reap_orphans() -> int:
    """SIGTERM any `sliver-client --rc` processes still alive from a previous
    BFF run. Returns the count of signals sent. Best-effort: failures are
    logged but don't abort startup."""
    try:
        result = subprocess.run(
            ["pgrep", "-u", str(os.getuid()), "-f", "sliver-client --rc"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("orphan reaper pgrep failed: %s", e)
        return 0
    pids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pids.append(int(line))
        except ValueError:
            continue
    killed = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except (ProcessLookupError, PermissionError) as e:
            log.debug("could not SIGTERM orphan pid %s: %s", pid, e)
    if killed:
        log.info("reaped %d orphan sliver-client --rc subprocess(es)", killed)
    return killed


# Singleton
tunnel_registry = TunnelRegistry()
