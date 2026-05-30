"""Files / Loot + ps-fix coverage (Phase 6a).

Two layers:
  * Pure-function tests on _ls_result_dict / _ps_result_dict using REAL
    sliver_pb2 protos. These run the real _pb_to_dict and would catch the
    repeated-field stringification bug (str(container) → entries silently
    dropped). The route-level fixture monkeypatches _pb_to_dict, so it can't.
  * Route-level tests via TestClient with the sliver-py client mocked.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── Pure-function: real-proto extraction ───────────────────────────

def test_ls_result_dict_parses_real_proto_entries():
    from routes.implants import _ls_result_dict
    from sliver.pb.sliverpb import sliver_pb2 as s
    ls = s.Ls(Path="/tmp")
    ls.Files.add(Name="a.txt", Size=10, IsDir=False, ModTime=1700000000)
    ls.Files.add(Name="sub", IsDir=True)
    out = _ls_result_dict(ls)
    assert out["path"] == "/tmp"
    assert [e["name"] for e in out["entries"]] == ["a.txt", "sub"]
    assert out["entries"][0]["size"] == 10
    assert out["entries"][0]["is_dir"] is False
    assert out["entries"][0]["mod_time"] == 1700000000
    assert out["entries"][1]["is_dir"] is True


def test_ls_result_dict_empty_proto():
    from routes.implants import _ls_result_dict
    from sliver.pb.sliverpb import sliver_pb2 as s
    out = _ls_result_dict(s.Ls(Path="/empty"))
    assert out == {"path": "/empty", "entries": []}


def test_ps_result_dict_parses_real_proto():
    from routes.implants import _ps_result_dict
    from sliver.pb.sliverpb import sliver_pb2 as s
    ps = s.Ps()
    ps.Processes.add(Pid=42, Ppid=1, Executable="explorer.exe", Owner="user")
    out = _ps_result_dict(ps)
    assert out["processes"] == [
        {"pid": 42, "ppid": 1, "name": "explorer.exe", "owner": "user"},
    ]


def test_ps_result_dict_parses_session_list():
    """InteractiveSession.ps() returns list(processes.Processes) directly."""
    from routes.implants import _ps_result_dict
    from sliver.pb.sliverpb import sliver_pb2 as s
    ps = s.Ps()
    ps.Processes.add(Pid=7, Ppid=1, Executable="bash", Owner="root")
    out = _ps_result_dict(list(ps.Processes))
    assert out["processes"] == [
        {"pid": 7, "ppid": 1, "name": "bash", "owner": "root"},
    ]


def test_ps_result_dict_empty():
    from routes.implants import _ps_result_dict
    from sliver.pb.sliverpb import sliver_pb2 as s
    assert _ps_result_dict([]) == {"processes": []}
    assert _ps_result_dict(s.Ps()) == {"processes": []}


# ── _ps_via_beacon registers a Future under the real Sliver TaskID ──

def test_ps_via_beacon_registers_future():
    from routes.implants import _ps_via_beacon

    bcn = MagicMock()
    bcn.timeout = 30
    bcn.beacon_tasks = {}
    bcn._request = lambda pb: pb
    resp = MagicMock()
    resp.Response.TaskID = "sliver-task-abc"
    bcn._stub.Ps = AsyncMock(return_value=resp)

    fut = asyncio.run(_ps_via_beacon(bcn))
    assert asyncio.isfuture(fut)
    assert "sliver-task-abc" in bcn.beacon_tasks
    assert bcn.beacon_tasks["sliver-task-abc"][0] is fut


# ── Route-level fixtures (mocked sliver-py) ────────────────────────

class _FakeImplant:
    def __init__(self, ID: str, hostname: str = "winbox"):
        self.ID = ID
        self.Name = "X"
        self.Hostname = hostname
        self.Username = "user"
        self.OS = "windows"
        self.Arch = "amd64"
        self.Transport = "mtls"
        self.RemoteAddress = "10.1.0.7:1000"
        self.Pid = 100
        self.UID = "0"; self.GID = "0"
        self.LastCheckin = 0
        self.IsDead = False
        self.Filename = ""
        self.ActiveC2 = ""
        self.NextCheckin = 0
        self.Interval = 60
        self.Jitter = 10
        self.TasksCount = 0
        self.TasksCountCompleted = 0


@pytest.fixture
def fake_client():
    c = MagicMock()
    c.sessions = AsyncMock(return_value=[])
    c.beacons = AsyncMock(return_value=[])
    c.jobs = AsyncMock(return_value=[])
    c.loot_all = AsyncMock(return_value=[])
    c.beacon_tasks = AsyncMock(return_value=[])
    return c


@pytest.fixture
def client(monkeypatch, fake_client):
    from sliver_client import hub
    monkeypatch.setattr(type(hub), "client", property(lambda self: fake_client))
    monkeypatch.setattr(hub, "_connected", True)

    def fake_pb(obj):
        if obj is None: return None
        if isinstance(obj, dict): return obj
        return {k: getattr(obj, k) for k in dir(obj)
                if not k.startswith("_") and not callable(getattr(obj, k, None))}
    monkeypatch.setattr("sliver_client._pb_to_dict", fake_pb)
    monkeypatch.setattr("routes.implants._pb_to_dict", fake_pb)

    import main
    with TestClient(main.app) as c:
        yield c


# ── Loot ────────────────────────────────────────────────────────────

def test_loot_empty_list(client, fake_client):
    fake_client.loot_all = AsyncMock(return_value=[])
    r = client.get("/api/loot")
    assert r.status_code == 200
    assert r.json() == []


def test_loot_missing_method_returns_empty(client, fake_client):
    # sliver-py 0.0.19 has no loot_all → AttributeError → [].
    fake_client.loot_all = AsyncMock(side_effect=AttributeError("no loot_all"))
    r = client.get("/api/loot")
    assert r.status_code == 200
    assert r.json() == []


# ── ls (unified) ────────────────────────────────────────────────────

def test_ls_on_session_happy(client, fake_client):
    from sliver.pb.sliverpb import sliver_pb2 as s
    sid = "11111111-1111-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    ls = s.Ls(Path="/home")
    ls.Files.add(Name="notes.txt", Size=5, IsDir=False)
    ls.Files.add(Name="docs", IsDir=True)
    interactive = MagicMock()
    interactive.ls = AsyncMock(return_value=ls)
    fake_client.interact_session = AsyncMock(return_value=interactive)

    r = client.post(f"/api/implants/{sid}/ls", json={"path": "/home"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "session"
    assert body["path"] == "/home"
    assert {e["name"] for e in body["entries"]} == {"notes.txt", "docs"}


def test_ls_unknown_implant_404(client, fake_client):
    fake_client.sessions.return_value = []
    fake_client.beacons.return_value = []
    r = client.post("/api/implants/nope/ls", json={"path": "."})
    assert r.status_code == 404


# ── ps (unified) ────────────────────────────────────────────────────

def test_ps_on_session_happy(client, fake_client):
    from sliver.pb.sliverpb import sliver_pb2 as s
    sid = "22222222-1111-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    ps = s.Ps()
    ps.Processes.add(Pid=99, Ppid=1, Executable="svchost.exe", Owner="SYSTEM")
    interactive = MagicMock()
    # sliver-py returns list(processes.Processes) from InteractiveSession.ps()
    interactive.ps = AsyncMock(return_value=list(ps.Processes))
    fake_client.interact_session = AsyncMock(return_value=interactive)

    r = client.post(f"/api/implants/{sid}/ps", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "session"
    assert body["processes"][0]["pid"] == 99
    assert body["processes"][0]["name"] == "svchost.exe"


def test_ps_on_beacon_does_not_error(client, fake_client):
    """Regression: before the fix, b.ps() raised 'list' object has no
    attribute 'Response' synchronously inside the runner, so the task went
    straight to error. With _ps_via_beacon the Ps RPC is queued and the task
    stays queued/running (the SDK listener that resolves it doesn't run here)."""
    bid = "33333333-2222-2222-2222-222222222222"
    fake_client.beacons.return_value = [_FakeImplant(bid)]
    interactive = MagicMock()
    interactive.beacon_tasks = {}
    interactive.timeout = 30
    interactive._request = lambda pb: pb
    resp = MagicMock()
    resp.Response.TaskID = "sliver-ps-task"
    interactive._stub.Ps = AsyncMock(return_value=resp)
    fake_client.interact_beacon = AsyncMock(return_value=interactive)

    r = client.post(f"/api/implants/{bid}/ps", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "beacon"
    tid = body["task_id"]
    state = None
    for _ in range(20):
        state = client.get(f"/api/tasks/{tid}").json()["state"]
        if state == "error":
            break
        time.sleep(0.01)
    assert state != "error", f"ps task errored: {client.get(f'/api/tasks/{tid}').json()}"
    # And the Ps RPC was actually queued under the real Sliver TaskID.
    assert "sliver-ps-task" in interactive.beacon_tasks


def test_ps_unknown_implant_404(client, fake_client):
    fake_client.sessions.return_value = []
    fake_client.beacons.return_value = []
    r = client.post("/api/implants/nope/ps", json={})
    assert r.status_code == 404


# ── download (unified) — unknown implant short-circuits ─────────────

def test_download_unknown_implant_404(client, fake_client):
    fake_client.sessions.return_value = []
    fake_client.beacons.return_value = []
    r = client.post("/api/implants/nope/download", json={"path": "/etc/hosts"})
    assert r.status_code == 404
