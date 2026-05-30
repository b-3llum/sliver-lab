"""Locate the operator gRPC config file.

Default: first *.cfg under ~/.sliver-client/configs/.
Override: SLIVER_CFG_PATH env var.
"""
from __future__ import annotations

import os
from pathlib import Path

# Load .env (backend/.env or the project-root .env) into the environment before
# any os.environ reads below. python-dotenv is already a dep; without this the
# .env file was inert. Existing env vars win (override=False), so an inline
# `VAR=… uvicorn …` still takes precedence.
try:
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:  # noqa: BLE001 — dotenv missing or unreadable; fall back to os env
    pass

CONFIG_DIR = Path.home() / ".sliver-client" / "configs"


def find_operator_config() -> Path:
    override = os.environ.get("SLIVER_CFG_PATH")
    if override:
        p = Path(override).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"SLIVER_CFG_PATH does not exist: {p}")
        return p

    if not CONFIG_DIR.is_dir():
        raise FileNotFoundError(
            f"No operator config dir at {CONFIG_DIR}. "
            "Generate one with `sliver-server operator …` or set SLIVER_CFG_PATH."
        )

    cfgs = sorted(CONFIG_DIR.glob("*.cfg"))
    if not cfgs:
        raise FileNotFoundError(f"No *.cfg files in {CONFIG_DIR}")
    return cfgs[0]


# tunables
RECONNECT_INITIAL_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0
EVENT_BUFFER_SIZE = 256


# ── avgen integration ─────────────────────────────────────────────
# Optional, user-supplied integration. The avgen implant builder is NOT shipped
# with this repo. Leave AVGEN_PATH empty to disable the Build tab's avgen panel
# (the backend reports avgen_present=false); point it at your own avgen.py to
# enable it.
AVGEN_PATH = Path(os.environ.get("AVGEN_PATH", "")).expanduser()
AVGEN_PYTHON = os.environ.get("AVGEN_PYTHON", "python3")
AVGEN_TIMEOUT = int(os.environ.get("AVGEN_TIMEOUT", "240"))  # seconds; msfvenom + mingw can be slow
AVGEN_BUILD_DIR = Path(os.environ.get("AVGEN_BUILD_DIR", "/tmp/sliverui-builds")).expanduser()


# ── BOF library ───────────────────────────────────────────────────
# Operator drops .o files (optionally grouped by category subdir) under
# $BOF_DIR. Default mirrors sliver-server's armory layout.
BOF_DIR_ENV = "BOF_DIR"
BOF_DIR_DEFAULT = Path.home() / ".sliver" / "bofs"


def bof_dir() -> tuple[Path, bool]:
    """Return (path, env_set). The path is always returned even if missing,
    so the UI can show "drop files at <path>" without a second roundtrip."""
    raw = os.environ.get(BOF_DIR_ENV)
    if raw:
        return Path(raw).expanduser(), True
    return BOF_DIR_DEFAULT, False


# Legacy: kept so the old per-BOF env vars still resolve for callers that
# haven't migrated. Returns None when unset.
def bof_path(env_var: str) -> Path | None:
    p = os.environ.get(env_var)
    if not p:
        return None
    path = Path(p).expanduser()
    return path if path.is_file() else None


# ── Persistent listener escape hatch ──────────────────────────────
# sliver-server stores listener config in this sqlite db. When the runtime
# state diverges from the persisted rows (server restart with stale rows),
# new listeners hit "port in use" and the only fix is to forget the row.
SLIVER_DB_PATH = Path(os.environ.get("SLIVER_DB_PATH", str(Path.home() / ".sliver" / "sliver.db"))).expanduser()


# ── Audit log ─────────────────────────────────────────────────────
# sliver-server appends one JSON object per line here. Read-only tail surface.
AUDIT_LOG_PATH = Path(
    os.environ.get("AUDIT_LOG_PATH", str(Path.home() / ".sliver" / "logs" / "audit.json"))
).expanduser()

# Routine read-only RPCs the UI (and CLI) poll constantly — hidden by default
# so the operator-action signal isn't drowned. Matched against the action's
# trailing method name. Override with AUDIT_POLLING_ACTIONS (comma-separated).
_DEFAULT_POLLING_ACTIONS = (
    "GetSessions,GetBeacons,GetJobs,GetOperators,GetVersion,"
    "GetSessionLogs,GetBeaconTasks"
)


def audit_polling_actions() -> set[str]:
    raw = os.environ.get("AUDIT_POLLING_ACTIONS", _DEFAULT_POLLING_ACTIONS)
    return {a.strip() for a in raw.split(",") if a.strip()}


# ── ngrok public exposure (Phase E) ───────────────────────────────
# Required to open ngrok tunnels. Read at request time (not cached) so the
# operator can add it to .env and restart without further code changes.
def ngrok_authtoken() -> str:
    return os.environ.get("NGROK_AUTHTOKEN", "").strip()
