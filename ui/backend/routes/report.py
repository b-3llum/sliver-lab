"""Engagement-reporting layer.

Turns the data the C2 already recorded — the sliver-server audit log plus the
current live implant state — into a purple-team deliverable: an operator
activity timeline, an ATT&CK technique breakdown, and the set of footholds, in
both structured JSON (`GET /api/report`) and a downloadable Markdown document
(`GET /api/report/markdown`).

This is documentation/reporting only: it reads existing records and live
session/beacon metadata, never generates implant behaviour. The ATT&CK mapping
is a classification aid so the blue team knows which detections to validate; it
is deliberately conservative and easy to extend (see ATTACK_MAP).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query, Response

from config import AUDIT_LOG_PATH
from models import (
    AttackTechnique,
    FootholdInfo,
    ReportData,
    ReportSummary,
    TechniqueCount,
    TimelineItem,
)
from routes.audit import _action_tail, scan_entries
from sliver_client import _pb_to_dict, hub

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/report", tags=["report"])

# Audit scans never need more than this; mirrors the audit route's own cap.
_LIMIT_CAP = 5000

_T = AttackTechnique

# Maps a normalized (lowercased) sliver RPC method tail OR a task-registry kind
# to an ATT&CK technique. Keys cover both because operator actions surface as
# RPC methods in the audit log ("Execute", "Ls") and as task kinds elsewhere
# ("exec", "ls"). Unmapped actions still appear in the timeline, just untagged.
ATTACK_MAP: dict[str, AttackTechnique] = {
    # ── Execution ──
    "execute": _T(id="T1059", name="Command and Scripting Interpreter", tactic="Execution"),
    "exec": _T(id="T1059", name="Command and Scripting Interpreter", tactic="Execution"),
    "shell": _T(id="T1059", name="Command and Scripting Interpreter", tactic="Execution"),
    "interactive": _T(id="T1059", name="Command and Scripting Interpreter", tactic="Execution"),
    "executeassembly": _T(id="T1620", name="Reflective Code Loading", tactic="Defense Evasion"),
    "executeshellcode": _T(id="T1055", name="Process Injection", tactic="Defense Evasion"),
    "sideload": _T(id="T1574.002", name="Hijack Execution Flow: DLL Side-Loading", tactic="Defense Evasion"),
    "spawndll": _T(id="T1055.001", name="Process Injection: DLL Injection", tactic="Defense Evasion"),
    "migrate": _T(id="T1055", name="Process Injection", tactic="Defense Evasion"),
    "psexec": _T(id="T1569.002", name="System Services: Service Execution", tactic="Lateral Movement"),
    # ── Discovery ──
    "ls": _T(id="T1083", name="File and Directory Discovery", tactic="Discovery"),
    "pwd": _T(id="T1083", name="File and Directory Discovery", tactic="Discovery"),
    "ps": _T(id="T1057", name="Process Discovery", tactic="Discovery"),
    "netstat": _T(id="T1049", name="System Network Connections Discovery", tactic="Discovery"),
    "ifconfig": _T(id="T1016", name="System Network Configuration Discovery", tactic="Discovery"),
    "info": _T(id="T1082", name="System Information Discovery", tactic="Discovery"),
    "getuid": _T(id="T1033", name="System Owner/User Discovery", tactic="Discovery"),
    "getgid": _T(id="T1033", name="System Owner/User Discovery", tactic="Discovery"),
    # ── Collection ──
    "cat": _T(id="T1005", name="Data from Local System", tactic="Collection"),
    "download": _T(id="T1005", name="Data from Local System", tactic="Collection"),
    "screenshot": _T(id="T1113", name="Screen Capture", tactic="Collection"),
    # ── Privilege escalation / credential access ──
    "getsystem": _T(id="T1134", name="Access Token Manipulation", tactic="Privilege Escalation"),
    "impersonate": _T(id="T1134.001", name="Access Token Manipulation: Token Impersonation/Theft", tactic="Privilege Escalation"),
    "runas": _T(id="T1134", name="Access Token Manipulation", tactic="Privilege Escalation"),
    "maketoken": _T(id="T1134.003", name="Access Token Manipulation: Make and Impersonate Token", tactic="Privilege Escalation"),
    # ── Command & control ──
    "upload": _T(id="T1105", name="Ingress Tool Transfer", tactic="Command and Control"),
    "portfwd": _T(id="T1572", name="Protocol Tunneling", tactic="Command and Control"),
    "rportfwd": _T(id="T1572", name="Protocol Tunneling", tactic="Command and Control"),
    "socks5": _T(id="T1090", name="Proxy", tactic="Command and Control"),
    "starthttplistener": _T(id="T1071.001", name="Application Layer Protocol: Web Protocols", tactic="Command and Control"),
    "starthttpslistener": _T(id="T1071.001", name="Application Layer Protocol: Web Protocols", tactic="Command and Control"),
    "startmtlslistener": _T(id="T1071", name="Application Layer Protocol", tactic="Command and Control"),
    "startdnslistener": _T(id="T1071.004", name="Application Layer Protocol: DNS", tactic="Command and Control"),
    # ── Resource development ──
    "generate": _T(id="T1587.001", name="Develop Capabilities: Malware", tactic="Resource Development"),
    "generateexternal": _T(id="T1587.001", name="Develop Capabilities: Malware", tactic="Resource Development"),
    "regenerate": _T(id="T1587.001", name="Develop Capabilities: Malware", tactic="Resource Development"),
    # ── Defense evasion / impact ──
    "rm": _T(id="T1070.004", name="Indicator Removal: File Deletion", tactic="Defense Evasion"),
}


def classify(name: str) -> AttackTechnique | None:
    """Map an action label (RPC method tail or task kind) to a technique."""
    if not name:
        return None
    return ATTACK_MAP.get(name.strip().lower())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _g(d: dict[str, Any], *keys: str) -> str:
    """First non-empty value among `keys`, as a string. sliver-py casing
    varies by version, so callers pass both ("Hostname", "hostname")."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


async def _collect_footholds() -> list[FootholdInfo]:
    """Live sessions + beacons from the teamserver. Best-effort: if the hub is
    offline the report still renders, just without a footholds section."""
    out: list[FootholdInfo] = []
    for kind, getter in (("session", "sessions"), ("beacon", "beacons")):
        try:
            items = await getattr(hub.client, getter)()
        except Exception:  # noqa: BLE001 — hub offline / RPC failure; report degrades gracefully
            items = []
        for it in items or []:
            d = _pb_to_dict(it) or {}
            out.append(FootholdInfo(
                kind=kind,  # type: ignore[arg-type]
                identifier=_g(d, "ID", "id"),
                host=_g(d, "Hostname", "hostname"),
                user=_g(d, "Username", "username"),
                os=_g(d, "OS", "os"),
                arch=_g(d, "Arch", "arch"),
                transport=_g(d, "Transport", "transport"),
                remote_address=_g(d, "RemoteAddress", "remote_address"),
            ))
    return out


async def _build_report(
    engagement: str, since: str | None, include_polling: bool, limit: int,
) -> ReportData:
    engagement = engagement.strip() or "Untitled engagement"

    entries: list[Any] = []
    if AUDIT_LOG_PATH.is_file():
        try:
            entries, _ = scan_entries(
                AUDIT_LOG_PATH, since=since, include_polling=include_polling, limit=limit,
            )
        except OSError as e:
            log.warning("report: audit read failed: %s", e)
            entries = []
    # scan_entries yields newest-first; a report reads better chronologically.
    entries.reverse()

    timeline: list[TimelineItem] = []
    operators: list[str] = []
    action_types: dict[str, int] = {}
    # technique id → [technique, count]
    tech_counts: dict[str, list[Any]] = {}

    for e in entries:
        method = _action_tail(e.action)
        tech = classify(method)
        label = method or e.action or "—"
        timeline.append(TimelineItem(
            timestamp=e.timestamp, operator=e.operator,
            action=label, target=e.target, technique=tech,
        ))
        if e.operator and e.operator not in operators:
            operators.append(e.operator)
        action_types[label] = action_types.get(label, 0) + 1
        if tech is not None:
            slot = tech_counts.get(tech.id)
            if slot is None:
                tech_counts[tech.id] = [tech, 1]
            else:
                slot[1] += 1

    techniques = [
        TechniqueCount(id=t.id, name=t.name, tactic=t.tactic, count=c)
        for t, c in sorted(tech_counts.values(), key=lambda tc: (-tc[1], tc[0].id))
    ]

    footholds = await _collect_footholds()
    sessions = sum(1 for f in footholds if f.kind == "session")
    beacons = sum(1 for f in footholds if f.kind == "beacon")

    summary = ReportSummary(
        operator_action_count=len(timeline),
        operators=operators,
        session_count=sessions,
        beacon_count=beacons,
        distinct_technique_count=len(techniques),
        action_types=action_types,
    )
    return ReportData(
        engagement=engagement,
        generated_at=_now_iso(),
        window_since=since,
        summary=summary,
        techniques=techniques,
        footholds=footholds,
        timeline=timeline,
    )


def _esc(s: str) -> str:
    """Escape a cell value for a Markdown table."""
    return (s or "—").replace("|", "\\|").replace("\n", " ")


def render_markdown(r: ReportData) -> str:
    lines: list[str] = [
        f"# Engagement Report — {r.engagement}",
        "",
        f"- **Generated:** {r.generated_at}",
        f"- **Window:** {r.window_since or 'full audit log'}",
        f"- **Operator actions:** {r.summary.operator_action_count}",
        f"- **Operators:** {', '.join(r.summary.operators) or '—'}",
        f"- **Active footholds:** {r.summary.session_count} session(s), "
        f"{r.summary.beacon_count} beacon(s)",
        f"- **Distinct ATT&CK techniques:** {r.summary.distinct_technique_count}",
        "",
        "> Compiled by SliverUI from the sliver-server audit log and live implant",
        "> state. ATT&CK mappings are an aid for blue-team detection validation,",
        "> not an authoritative classification.",
        "",
        "## ATT&CK Techniques Observed",
        "",
    ]
    if r.techniques:
        lines.append("| Technique | ID | Tactic | Count |")
        lines.append("| --- | --- | --- | --- |")
        for t in r.techniques:
            lines.append(f"| {_esc(t.name)} | {t.id} | {_esc(t.tactic)} | {t.count} |")
    else:
        lines.append("_No mapped techniques in this window._")

    lines += ["", "## Footholds", ""]
    if r.footholds:
        lines.append("| Kind | Host | User | OS/Arch | Transport | Remote |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for f in r.footholds:
            osarch = "/".join(x for x in (f.os, f.arch) if x) or "—"
            lines.append(
                f"| {f.kind} | {_esc(f.host)} | {_esc(f.user)} | {_esc(osarch)} "
                f"| {_esc(f.transport)} | {_esc(f.remote_address)} |"
            )
    else:
        lines.append("_No live sessions or beacons (teamserver offline or no active implants)._")

    lines += ["", "## Operator Activity Timeline", ""]
    if r.timeline:
        lines.append("| Time | Operator | Action | Technique | Target |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in r.timeline:
            tech = f"{item.technique.id} {item.technique.name}" if item.technique else "—"
            lines.append(
                f"| {_esc(item.timestamp)} | {_esc(item.operator)} | `{_esc(item.action)}` "
                f"| {_esc(tech)} | {_esc(item.target)} |"
            )
    else:
        lines.append("_No operator actions recorded in this window._")

    lines.append("")
    return "\n".join(lines)


def _slug(name: str) -> str:
    s = "".join(c if c.isalnum() else "-" for c in name.lower())
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-") or "engagement"


@router.get("", response_model=ReportData)
async def get_report(
    engagement: str = Query(default=""),
    since: str | None = Query(default=None),
    include_polling: bool = Query(default=False),
    limit: int = Query(default=2000),
) -> ReportData:
    limit = max(1, min(limit, _LIMIT_CAP))
    return await _build_report(engagement, since, include_polling, limit)


@router.get("/markdown")
async def get_report_markdown(
    engagement: str = Query(default=""),
    since: str | None = Query(default=None),
    include_polling: bool = Query(default=False),
    limit: int = Query(default=2000),
) -> Response:
    limit = max(1, min(limit, _LIMIT_CAP))
    report = await _build_report(engagement, since, include_polling, limit)
    md = render_markdown(report)
    headers = {"Content-Disposition": f'attachment; filename="{_slug(report.engagement)}-report.md"'}
    return Response(content=md, media_type="text/markdown; charset=utf-8", headers=headers)
