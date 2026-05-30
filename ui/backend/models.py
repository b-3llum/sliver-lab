"""Response models for the BFF.

Mirrors the subset of sliver-py protobuf fields the frontend needs.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionInfo(BaseModel):
    id: str = Field(..., alias="ID")
    name: str = ""
    hostname: str = ""
    username: str = ""
    uid: str = ""
    gid: str = ""
    os: str = ""
    arch: str = ""
    transport: str = ""
    remote_address: str = ""
    pid: int = 0
    filename: str = ""
    last_checkin: int = 0
    active_c2: str = ""
    is_dead: bool = False

    model_config = {"populate_by_name": True}


class BeaconInfo(BaseModel):
    id: str = Field(..., alias="ID")
    name: str = ""
    hostname: str = ""
    username: str = ""
    os: str = ""
    arch: str = ""
    transport: str = ""
    remote_address: str = ""
    pid: int = 0
    next_checkin: int = 0
    interval: int = 0
    jitter: int = 0
    tasks_count: int = 0
    tasks_count_completed: int = 0
    # True when the beacon is overdue by >2× its interval (matches the graph's
    # stale-edge logic). Derived server-side so the frontend doesn't recompute.
    stale: bool = False

    model_config = {"populate_by_name": True}


class NgrokTunnel(BaseModel):
    """An open ngrok TCP tunnel fronting a local listener port."""
    id: str
    listener_port: int
    public_url: str            # tcp://X.tcp.ngrok.io:NNNNN
    public_host: str           # X.tcp.ngrok.io
    public_port: int           # NNNNN
    kind: Literal["tcp"] = "tcp"
    started_at: str            # iso8601


class NgrokCreateRequest(BaseModel):
    listener_port: int


class JobInfo(BaseModel):
    id: int = Field(..., alias="ID")
    name: str = ""
    description: str = ""
    protocol: str = ""
    port: int = 0
    domains: list[str] = []
    # Populated by the listeners route when an ngrok tunnel fronts this port.
    public_exposure: NgrokTunnel | None = None

    model_config = {"populate_by_name": True}


class ListenerCreate(BaseModel):
    kind: Literal["http", "https", "mtls", "dns"]
    host: str = "0.0.0.0"
    port: int
    domain: str | None = None
    website: str | None = None
    persistent: bool = False


class PersistentListener(BaseModel):
    """Row from sliver.db that has no live job — usually a leftover from a
    crashed teamserver. Reading these lets the UI offer a 'forget' button so
    the user can recover from port-in-use errors without touching sqlite."""
    job_id: int
    kind: str
    host: str
    port: int
    created_at: str | None = None


class ListenerConflict(BaseModel):
    """Body of the 409 returned when a port is already bound."""
    kind: str
    host: str
    port: int
    message: str
    hint: str


class ExecRequest(BaseModel):
    cmd: str
    args: list[str] = []
    timeout: int = 30
    output: bool = True


class ExecResponse(BaseModel):
    stdout: str = ""
    stderr: str = ""
    status: int = 0
    pid: int = 0


class FileListRequest(BaseModel):
    path: str = "."


class FileEntry(BaseModel):
    name: str
    size: int = 0
    mode: str = ""
    mod_time: int = 0
    is_dir: bool = False


class FileListResponse(BaseModel):
    path: str
    entries: list[FileEntry] = []


class LootInfo(BaseModel):
    id: str = Field(..., alias="ID")
    name: str = ""
    type: str = ""
    file_type: str = ""
    credential_type: str = ""

    model_config = {"populate_by_name": True}


class ConnState(BaseModel):
    connected: bool
    server_version: str | None = None
    cfg_path: str | None = None
    last_error: str | None = None


class AuditEntry(BaseModel):
    """One normalized audit row. sliver writes `time`+`level` plus a nested
    JSON string `msg` carrying user/method/remote_ip/request — we promote the
    interesting fields and keep the remainder under `details`."""
    timestamp: str = ""
    operator: str = ""
    action: str = ""
    target: str = ""
    details: dict[str, Any] = {}


class AuditResponse(BaseModel):
    entries: list[AuditEntry]


class OperatorInfo(BaseModel):
    """sliver-py's Operator proto only carries Name + Online — no joined_at or
    action count — so that's all we surface (we don't fabricate fields)."""
    name: str
    online: bool = False


class OperatorMe(BaseModel):
    name: str


class EventEnvelope(BaseModel):
    """Pushed over /events WebSocket."""
    type: str
    data: dict[str, Any] = {}


# ── Build (avgen integration) ──────────────────────────────────────

class BuildField(BaseModel):
    """One avgen flag, normalized for UI rendering."""
    name: str             # Python attr (e.g. "lhost", "patch_amsi")
    flag: str             # CLI flag (e.g. "--lhost", "--patch-amsi")
    kind: Literal["string", "int", "bool", "choice"]
    default: Any = None
    required: bool = False
    choices: list[str] | None = None
    metavar: str | None = None
    help: str = ""


class BuildGroup(BaseModel):
    name: str
    description: str | None = None
    exclusive: bool = False     # at most one field truthy
    fields: list[BuildField]


class BuildSchema(BaseModel):
    avgen_path: str
    avgen_present: bool
    groups: list[BuildGroup]


class BuildRequest(BaseModel):
    """Flat {flag_name: value} bag from the form."""
    options: dict[str, Any]


# ── BOF library ────────────────────────────────────────────────────

class BofEntry(BaseModel):
    name: str
    category: str               # subdir under $BOF_DIR (or "uncategorized")
    description: str = ""       # currently empty; reserved for future manifest files
    args_help: str = ""
    path_env: str = ""          # legacy: empty for dir-scanned entries
    path: str | None = None
    available: bool = True      # only listed when on disk, so always True


class BofLibrary(BaseModel):
    """Metadata about the configured BOF directory — used by the UI to render
    a 'how to populate' hint when the directory is empty or unset."""
    dir: str
    env_set: bool       # $BOF_DIR was explicitly set vs. the default
    exists: bool
    count: int


class BofRunCommand(BaseModel):
    """Result of POST /api/bofs/{name}/build_command — Sliver CLI line.

    BOF execution requires Sliver's coff-loader extension installed in the
    target's armory. Rather than reimplement the COFF protocol over sliver-py,
    we emit the exact `inline-execute` command the operator pastes into the
    Sliver console.
    """
    name: str
    session_id: str
    sliver_command: str
    note: str = ""


# ── Malleable C2 profile presets ───────────────────────────────────

class ProfilePreset(BaseModel):
    name: str
    description: str
    category: str               # e.g. "cdn-mimicry", "update-traffic", "generic"
    yaml: str                   # full Sliver http-c2 config blob


# ── Tunnels (portfwd / rportfwd / socks5) ──────────────────────────

class TunnelCreatePortfwd(BaseModel):
    bind_addr: str
    bind_port: int
    remote_addr: str
    remote_port: int


class TunnelCreateSocks5(BaseModel):
    bind_addr: str
    bind_port: int


class TunnelRecord(BaseModel):
    """Public shape of a tunnel as returned to the UI. The frontend
    distinguishes kinds by which list bucket it sits in."""
    id: str
    kind: Literal["portfwd", "rportfwd", "socks5"]
    session_id: str
    bind_addr: str
    bind_port: int
    remote_addr: str = ""     # empty for socks5
    remote_port: int = 0      # 0 for socks5
    started_at: str           # iso8601
    marker_seen: bool


class TunnelList(BaseModel):
    portfwds: list[TunnelRecord]
    rportfwds: list[TunnelRecord]
    socks5: list[TunnelRecord]


# ── C2 topology graph ──────────────────────────────────────────────

class GraphNode(BaseModel):
    id: str
    kind: Literal["teamserver", "listener", "beacon", "session", "host", "unknown-listener"]
    label: str
    meta: dict[str, Any] = {}


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: Literal["structural", "session", "beacon"]


class GraphSnapshot(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    generated_at: str  # iso8601


# ── Implant console (unified session+beacon API) ───────────────────

class ImplantCapabilities(BaseModel):
    """Per-implant action manifest the frontend uses to enable buttons."""
    exec: bool = True
    ls: bool = True
    cat: bool = True
    ps: bool = True
    screenshot: bool = True
    download: bool = True
    kill: bool = True
    interactive: bool = False         # True for sessions, False for beacons
    promote_to_session: bool = False  # True for beacons (can call /interactive)
    tunneling: bool = False           # True for sessions only (portfwd/socks5/etc.)


class ImplantInfo(BaseModel):
    kind: Literal["session", "beacon"]
    info: dict[str, Any]
    capabilities: ImplantCapabilities


class ImplantExecRequest(BaseModel):
    argv: list[str]
    timeout_s: int = 30


class SessionExecResponse(BaseModel):
    kind: Literal["session"] = "session"
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0


class BeaconTaskResponse(BaseModel):
    kind: Literal["beacon"] = "beacon"
    task_id: str
    queued_at: str


class TaskQueuedResponse(BaseModel):
    """Async task queued for an implant. `kind` reflects the *implant* (session
    vs beacon), not the task type — screenshot/download are always async even
    for sessions, so the label must come from the resolved implant kind."""
    kind: Literal["session", "beacon"]
    task_id: str
    queued_at: str


class ImplantLsRequest(BaseModel):
    path: str = "."


class ImplantPathRequest(BaseModel):
    path: str


# ── Task registry (in-process) ─────────────────────────────────────

TaskState = Literal["queued", "running", "complete", "error"]
TaskResultKind = Literal[
    "text", "exec", "ls", "ps", "screenshot", "download", "upload", "kill",
    "interactive", "none",
]


class SessionUploadResponse(BaseModel):
    """Synchronous result for /api/implants/{session_id}/upload."""
    kind: Literal["session"] = "session"
    bytes_written: int
    dest_path: str


class TaskStatus(BaseModel):
    task_id: str
    state: TaskState
    kind: str                       # task action ("exec", "ls", "screenshot", ...)
    implant_id: str
    implant_kind: str               # "session" | "beacon"
    queued_at: str
    started_at: str | None = None
    completed_at: str | None = None
    result_kind: TaskResultKind | None = None
    result: Any = None              # text/structured payload (binary served via /result)
    error: str | None = None


# ── Sliver shellcode generation (for build pipeline integration) ───

class GenerateShellcodeRequest(BaseModel):
    """Generate a Sliver beacon as raw shellcode, returned as bytes."""
    name: str | None = None
    arch: Literal["amd64", "386"] = "amd64"
    os: Literal["windows"] = "windows"
    format: Literal["shellcode"] = "shellcode"
    transport: Literal["mtls", "http", "https", "dns"] = "mtls"
    callback_host: str
    callback_port: int
