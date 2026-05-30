"""C2 topology graph.

Composes a single-screen view of the teamserver → listeners → implants → hosts
relationship by reusing the existing listener/session/beacon route handlers.
No extra fetches, no duplicated filtering — if the listener filter changes,
the graph follows.

Edge resolution rules:
  - implant.transport in {mtls,http,https,dns,wg} → match listener by `name`.
  - When >1 listener of the same kind, prefer the one whose port equals the
    implant's remote_address port if parseable; otherwise round-robin.
  - When no matching listener of that kind exists, route to a synthetic
    `unknown-listener` node.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from itertools import cycle

from fastapi import APIRouter, HTTPException

from models import BeaconInfo, GraphEdge, GraphNode, GraphSnapshot, JobInfo, SessionInfo
from routes import beacons as beacons_route
from routes import listeners as listeners_route
from routes import sessions as sessions_route
from sliver_client import hub

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/graph", tags=["graph"])

TS_ID = "ts"
UNKNOWN_PREFIX = "unknown-listener:"


def _listener_id(j: JobInfo) -> str:
    return f"listener:{j.id}"


def _beacon_id(b: BeaconInfo) -> str:
    return f"beacon:{b.id}"


def _session_id(s: SessionInfo) -> str:
    return f"session:{s.id}"


def _host_id(hostname: str) -> str:
    return f"host:{hostname.lower()}"


def _parse_port(remote_address: str) -> int | None:
    """Pull the port number off "host:port" (IPv4) or "[host]:port" (IPv6).
    Returns None for empty/malformed input. Used only as a tiebreaker when
    multiple listeners of the same kind exist."""
    if not remote_address:
        return None
    s = remote_address.rsplit(":", 1)
    if len(s) != 2:
        return None
    try:
        return int(s[1])
    except ValueError:
        return None


def _build_listener_buckets(listeners: list[JobInfo]) -> dict[str, list[JobInfo]]:
    """Group listeners by lowercased name (kind), so we can pick by port or
    round-robin within a kind."""
    by_kind: dict[str, list[JobInfo]] = {}
    for j in listeners:
        kind = (j.name or "").lower()
        if not kind:
            continue
        by_kind.setdefault(kind, []).append(j)
    return by_kind


def _match_listener(
    transport: str,
    remote_address: str,
    by_kind: dict[str, list[JobInfo]],
    round_robin: dict[str, cycle],
) -> JobInfo | None:
    kind = (transport or "").lower()
    cands = by_kind.get(kind, [])
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    port = _parse_port(remote_address)
    if port is not None:
        for j in cands:
            if j.port == port:
                return j
    rr = round_robin.get(kind)
    if rr is None:
        rr = cycle(cands)
        round_robin[kind] = rr
    return next(rr)


def _unknown_listener_node(transport: str) -> GraphNode:
    kind = (transport or "?").lower()
    return GraphNode(
        id=f"{UNKNOWN_PREFIX}{kind}",
        kind="unknown-listener",
        label=f"unknown {kind}",
        meta={"transport": kind, "reason": "no matching listener found for this transport kind"},
    )


@router.get("", response_model=GraphSnapshot)
async def get_graph() -> GraphSnapshot:
    try:
        listeners: list[JobInfo] = await listeners_route.list_listeners()
        beacon_list: list[BeaconInfo] = await beacons_route.list_beacons()
        session_list: list[SessionInfo] = await sessions_route.list_sessions()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"graph compose failed: {e}")

    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    # Teamserver root
    state = hub.state()
    nodes[TS_ID] = GraphNode(
        id=TS_ID,
        kind="teamserver",
        label="teamserver",
        meta={
            "connected": state.connected,
            "server_version": state.server_version,
            "cfg_path": state.cfg_path,
        },
    )

    # Listeners — teamserver → listener (structural)
    for j in listeners:
        nid = _listener_id(j)
        kind = (j.name or "?").lower()
        nodes[nid] = GraphNode(
            id=nid,
            kind="listener",
            label=f"{kind}:{j.port}",
            meta=j.model_dump(by_alias=True),
        )
        edges.append(GraphEdge(source=TS_ID, target=nid, kind="structural"))

    by_kind = _build_listener_buckets(listeners)
    round_robin: dict[str, cycle] = {}
    unknown_nodes_seen: set[str] = set()

    def _attach_implant(node: GraphNode, transport: str, remote_address: str, edge_kind: str) -> None:
        nodes[node.id] = node
        matched = _match_listener(transport, remote_address, by_kind, round_robin)
        if matched is not None:
            edges.append(GraphEdge(source=_listener_id(matched), target=node.id, kind=edge_kind))
        else:
            unk = _unknown_listener_node(transport)
            if unk.id not in unknown_nodes_seen:
                nodes[unk.id] = unk
                edges.append(GraphEdge(source=TS_ID, target=unk.id, kind="structural"))
                unknown_nodes_seen.add(unk.id)
            edges.append(GraphEdge(source=unk.id, target=node.id, kind=edge_kind))

    # Sessions — listener → session (session edge)
    for s in session_list:
        label = f"{s.username or '?'}@{s.hostname or '?'}"
        node = GraphNode(
            id=_session_id(s),
            kind="session",
            label=label,
            meta=s.model_dump(by_alias=True),
        )
        _attach_implant(node, s.transport, s.remote_address, "session")

    # Beacons — listener → beacon (beacon edge)
    for b in beacon_list:
        label = f"{b.username or '?'}@{b.hostname or '?'}"
        node = GraphNode(
            id=_beacon_id(b),
            kind="beacon",
            label=label,
            meta=b.model_dump(by_alias=True),
        )
        _attach_implant(node, b.transport, b.remote_address, "beacon")

    # Hosts — deduped by hostname (lowercased); structural edges from implant.
    hosts_seen: dict[str, GraphNode] = {}
    for s in session_list:
        if not s.hostname:
            continue
        hid = _host_id(s.hostname)
        if hid not in hosts_seen:
            hosts_seen[hid] = GraphNode(
                id=hid, kind="host", label=s.hostname,
                meta={"hostname": s.hostname, "os": s.os, "arch": s.arch},
            )
        edges.append(GraphEdge(source=_session_id(s), target=hid, kind="structural"))
    for b in beacon_list:
        if not b.hostname:
            continue
        hid = _host_id(b.hostname)
        if hid not in hosts_seen:
            hosts_seen[hid] = GraphNode(
                id=hid, kind="host", label=b.hostname,
                meta={"hostname": b.hostname, "os": b.os, "arch": b.arch},
            )
        edges.append(GraphEdge(source=_beacon_id(b), target=hid, kind="structural"))
    nodes.update(hosts_seen)

    # Deterministic ordering so client diffs are clean.
    sorted_nodes = sorted(nodes.values(), key=lambda n: n.id)
    sorted_edges = sorted(edges, key=lambda e: (e.source, e.target, e.kind))

    return GraphSnapshot(
        nodes=sorted_nodes,
        edges=sorted_edges,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
