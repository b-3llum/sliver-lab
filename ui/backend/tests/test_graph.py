"""Graph-route tests.

The graph composes /api/listeners + /api/beacons + /api/sessions in-process;
we drive it by stubbing the underlying route handlers so we don't have to
fake sliver-py protos or hit a real teamserver.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import BeaconInfo, JobInfo, SessionInfo  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    """Like the smoke-test fixture, but the graph route relies on the
    listener/session/beacon route handlers — we patch those directly so each
    test feeds the graph a curated topology."""
    from sliver_client import hub
    fake_state = type("State", (), {
        "model_dump": lambda self: {"connected": True, "server_version": "1.7.4",
                                     "cfg_path": "/tmp/op.cfg"},
        "connected": True, "server_version": "1.7.4", "cfg_path": "/tmp/op.cfg",
    })()
    monkeypatch.setattr(hub, "state", lambda: fake_state)
    monkeypatch.setattr(hub, "_connected", True)
    import main
    with TestClient(main.app) as c:
        yield c


def _set_topology(monkeypatch, *, listeners=None, beacons=None, sessions=None):
    from routes import beacons as br
    from routes import listeners as lr
    from routes import sessions as sr

    async def _listeners(): return listeners or []
    async def _beacons(): return beacons or []
    async def _sessions(): return sessions or []

    monkeypatch.setattr(lr, "list_listeners", _listeners)
    monkeypatch.setattr(br, "list_beacons", _beacons)
    monkeypatch.setattr(sr, "list_sessions", _sessions)

    # The graph route imports these symbols from the route modules; rebind
    # there too so monkeypatch sticks regardless of import path.
    from routes import graph as gr
    monkeypatch.setattr(gr.listeners_route, "list_listeners", _listeners)
    monkeypatch.setattr(gr.beacons_route, "list_beacons", _beacons)
    monkeypatch.setattr(gr.sessions_route, "list_sessions", _sessions)


def _job(job_id: int, name: str, port: int) -> JobInfo:
    return JobInfo(ID=job_id, name=name, description=f"{name} listener", protocol="tcp", port=port, domains=[])


def _beacon(bid: str, hostname: str, transport: str, remote: str = "10.1.0.7:9000") -> BeaconInfo:
    return BeaconInfo(
        ID=bid, name=f"B-{bid[:4]}", hostname=hostname, username="user",
        os="windows", arch="amd64", transport=transport, remote_address=remote,
        pid=1, next_checkin=0, interval=60, jitter=10, tasks_count=0, tasks_count_completed=0,
    )


def _session(sid: str, hostname: str, transport: str, remote: str = "10.1.0.7:9000") -> SessionInfo:
    return SessionInfo(
        ID=sid, name=f"S-{sid[:4]}", hostname=hostname, username="user", uid="0", gid="0",
        os="windows", arch="amd64", transport=transport, remote_address=remote,
        pid=2, filename="", last_checkin=0, active_c2="", is_dead=False,
    )


# ── tests ──────────────────────────────────────────────────────────


def test_node_ids_are_stable_across_calls(client, monkeypatch):
    """Same topology, two calls — node IDs and order must match."""
    _set_topology(monkeypatch,
                  listeners=[_job(3, "mtls", 8443)],
                  beacons=[_beacon("aaaaa", "winbox", "mtls")],
                  sessions=[])
    a = client.get("/api/graph").json()
    b = client.get("/api/graph").json()
    assert [n["id"] for n in a["nodes"]] == [n["id"] for n in b["nodes"]]
    assert [(e["source"], e["target"], e["kind"]) for e in a["edges"]] \
        == [(e["source"], e["target"], e["kind"]) for e in b["edges"]]


def test_implant_matches_listener_by_transport_and_port(client, monkeypatch):
    """Two http listeners, one beacon — match by port from remote_address."""
    _set_topology(monkeypatch,
                  listeners=[_job(10, "http", 80), _job(11, "http", 8080)],
                  beacons=[_beacon("bbbbb", "winbox", "http", remote="10.1.0.7:8080")],
                  sessions=[])
    body = client.get("/api/graph").json()
    edges = body["edges"]
    # Beacon must be attached to listener:11 (the port-8080 one), not :10.
    impl_edges = [e for e in edges if e["target"] == "beacon:bbbbb"]
    assert len(impl_edges) == 1
    assert impl_edges[0]["source"] == "listener:11"
    assert impl_edges[0]["kind"] == "beacon"


def test_implant_with_no_matching_listener_routes_to_unknown(client, monkeypatch):
    """Beacon transports as 'dns' but only an mtls listener exists."""
    _set_topology(monkeypatch,
                  listeners=[_job(3, "mtls", 8443)],
                  beacons=[_beacon("ccccc", "winbox", "dns")],
                  sessions=[])
    body = client.get("/api/graph").json()
    node_ids = {n["id"]: n["kind"] for n in body["nodes"]}
    assert "unknown-listener:dns" in node_ids
    assert node_ids["unknown-listener:dns"] == "unknown-listener"
    impl_edges = [e for e in body["edges"] if e["target"] == "beacon:ccccc"]
    assert len(impl_edges) == 1
    assert impl_edges[0]["source"] == "unknown-listener:dns"


def test_host_dedup_across_multiple_implants_on_same_hostname(client, monkeypatch):
    """Beacon + session both on 'winbox' should produce ONE host node."""
    _set_topology(monkeypatch,
                  listeners=[_job(3, "mtls", 8443)],
                  beacons=[_beacon("ddddd", "WinBox", "mtls")],   # capitalized
                  sessions=[_session("eeeee", "winbox", "mtls")])  # lowercase
    body = client.get("/api/graph").json()
    host_nodes = [n for n in body["nodes"] if n["kind"] == "host"]
    assert len(host_nodes) == 1
    assert host_nodes[0]["id"] == "host:winbox"
    # Both implants edge into the same host.
    host_edges = [e for e in body["edges"] if e["target"] == "host:winbox"]
    sources = sorted(e["source"] for e in host_edges)
    assert sources == ["beacon:ddddd", "session:eeeee"]


def test_empty_state_only_teamserver_and_listeners(client, monkeypatch):
    """No implants → just teamserver + listener kinds appear; no beacon,
    session, host, or unknown-listener nodes."""
    _set_topology(monkeypatch,
                  listeners=[_job(3, "mtls", 8443)],
                  beacons=[], sessions=[])
    body = client.get("/api/graph").json()
    kinds = {n["kind"] for n in body["nodes"]}
    assert kinds == {"teamserver", "listener"}
    # Exactly one structural edge teamserver → listener.
    assert body["edges"] == [{"source": "ts", "target": "listener:3", "kind": "structural"}]
