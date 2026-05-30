"""Unified implant route tests.

We mock the sliver-py client surface — interact_session, interact_beacon,
.execute, etc. — so the tests run with no teamserver and no network.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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


class _ExecRes:
    """Mimics the shape sliver-py returns from .execute()."""
    def __init__(self, stdout: bytes = b"win10-sandbox\\user\n", stderr: bytes = b"", status: int = 0):
        self.Stdout = stdout
        self.Stderr = stderr
        self.Status = status
        self.Pid = 0


@pytest.fixture
def fake_client():
    c = MagicMock()
    c.sessions = AsyncMock(return_value=[])
    c.beacons = AsyncMock(return_value=[])
    c.jobs = AsyncMock(return_value=[])
    c.loot_all = AsyncMock(return_value=[])
    return c


@pytest.fixture
def client(monkeypatch, fake_client):
    from sliver_client import hub
    monkeypatch.setattr(type(hub), "client", property(lambda self: fake_client))
    monkeypatch.setattr(hub, "_connected", True)
    # Force _pb_to_dict to walk attributes off our fake (it skips objects
    # without DESCRIPTOR otherwise).
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


def test_exec_on_session_is_synchronous(client, fake_client):
    """Session exec must return the session response shape immediately."""
    sid = "11111111-1111-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    interactive = MagicMock()
    interactive.execute = AsyncMock(return_value=_ExecRes())
    fake_client.interact_session = AsyncMock(return_value=interactive)

    r = client.post(f"/api/implants/{sid}/exec", json={"argv": ["whoami"]})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "session"
    assert "win10-sandbox\\user" in body["stdout"]
    assert body["exit_code"] == 0
    assert "duration_ms" in body


def test_exec_on_beacon_returns_task_id(client, fake_client):
    """Beacon exec must queue and return {task_id, queued_at}."""
    bid = "22222222-2222-2222-2222-222222222222"
    fake_client.beacons.return_value = [_FakeImplant(bid)]

    # The beacon runner runs in a background asyncio.Task. The runner will
    # await interact_beacon → execute; we make those resolve so it completes.
    interactive = MagicMock()
    interactive.execute = AsyncMock(return_value=_ExecRes())
    fake_client.interact_beacon = AsyncMock(return_value=interactive)

    r = client.post(f"/api/implants/{bid}/exec", json={"argv": ["whoami"]})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "beacon"
    assert "task_id" in body and "queued_at" in body
    # Give the runner a tick to complete on the same event loop the
    # TestClient uses, then check the task state.
    tid = body["task_id"]
    # The runner is a background task; TestClient runs each request in its
    # own event-loop-iteration, so we poll via the public endpoint.
    for _ in range(20):
        s = client.get(f"/api/tasks/{tid}").json()
        if s["state"] in ("complete", "error"):
            break
    assert s["state"] == "complete"
    assert s["result"]["exit_code"] == 0


def test_capabilities_differ_by_kind(client, fake_client):
    sid = "ssssssss-1111-1111-1111-111111111111"
    bid = "bbbbbbbb-2222-2222-2222-222222222222"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    fake_client.beacons.return_value = [_FakeImplant(bid)]

    sinfo = client.get(f"/api/implants/{sid}/info").json()
    binfo = client.get(f"/api/implants/{bid}/info").json()
    assert sinfo["kind"] == "session"
    assert binfo["kind"] == "beacon"
    assert sinfo["capabilities"]["interactive"] is True
    assert binfo["capabilities"]["interactive"] is False


def test_unknown_implant_id_404s(client, fake_client):
    fake_client.sessions.return_value = []
    fake_client.beacons.return_value = []
    for path in ("/api/implants/nope/info",
                 "/api/implants/nope/ls",
                 "/api/implants/nope/ps",
                 "/api/implants/nope/screenshot",
                 "/api/implants/nope/kill"):
        if path.endswith("/info"):
            r = client.get(path)
        elif path.endswith("/ls"):
            r = client.post(path, json={"path": "."})
        else:
            r = client.post(path, json={})
        assert r.status_code == 404, path


def test_task_state_transitions(client, fake_client):
    """Queue an exec, watch state move queued/running → complete."""
    bid = "cccccccc-2222-2222-2222-222222222222"
    fake_client.beacons.return_value = [_FakeImplant(bid)]
    # Make execute take a tick so we observe a non-terminal state at least
    # transiently — but TestClient may finish runner before we poll.
    interactive = MagicMock()

    async def slow_execute(*_a, **_k):
        await asyncio.sleep(0.01)
        return _ExecRes()
    interactive.execute = slow_execute
    fake_client.interact_beacon = AsyncMock(return_value=interactive)

    r = client.post(f"/api/implants/{bid}/exec", json={"argv": ["whoami"]})
    tid = r.json()["task_id"]
    # Poll until complete; assert we eventually reach it.
    state = None
    for _ in range(50):
        state = client.get(f"/api/tasks/{tid}").json()["state"]
        if state == "complete":
            break
    assert state == "complete"


# ── /interactive (beacon → session promotion) ──────────────────────

def test_promote_to_session_capability_flags(client, fake_client):
    sid = "ssssssss-9999-1111-1111-111111111111"
    bid = "bbbbbbbb-9999-2222-2222-222222222222"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    fake_client.beacons.return_value = [_FakeImplant(bid)]

    sinfo = client.get(f"/api/implants/{sid}/info").json()
    binfo = client.get(f"/api/implants/{bid}/info").json()
    assert sinfo["capabilities"]["promote_to_session"] is False
    assert binfo["capabilities"]["promote_to_session"] is True


def test_interactive_on_session_returns_400(client, fake_client):
    sid = "ssssssss-AAAA-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    r = client.post(f"/api/implants/{sid}/interactive")
    assert r.status_code == 400
    assert "already interactive" in r.json()["detail"].lower()


def test_interactive_on_unknown_id_returns_404(client, fake_client):
    fake_client.sessions.return_value = []
    fake_client.beacons.return_value = []
    r = client.post("/api/implants/nope/interactive")
    assert r.status_code == 404


def test_interactive_on_beacon_returns_task_id(client, fake_client):
    """Mock the underlying _stub.OpenSession call so the POST returns
    immediately with BeaconTaskResponse shape — the runner's await on the
    Future will hang in the background, which is fine for this assertion."""
    bid = "bbbbbbbb-AAAA-2222-2222-222222222222"
    fake_client.beacons.return_value = [_FakeImplant(bid)]

    # Mocked InteractiveBeacon: needs beacon_tasks dict, timeout, _request,
    # and an _stub.OpenSession that returns an awaitable with a Response.TaskID.
    interactive = MagicMock()
    interactive.beacon_tasks = {}
    interactive.timeout = 30
    interactive._request = lambda pb: pb
    fake_open_resp = MagicMock()
    fake_open_resp.Response.TaskID = "sliver-task-id-xyz"
    fake_open_resp.Response.Err = ""
    interactive._stub.OpenSession = AsyncMock(return_value=fake_open_resp)
    fake_client.interact_beacon = AsyncMock(return_value=interactive)

    r = client.post(f"/api/implants/{bid}/interactive")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "beacon"
    assert "task_id" in body and "queued_at" in body
    # State stays queued/running indefinitely in this test — that's expected;
    # the SDK's taskresult-events listener that completes the Future doesn't
    # run with our MagicMock channel.


# ── /upload (file push) ────────────────────────────────────────────

def test_upload_on_session_sync_happy(client, fake_client):
    sid = "uuuuuuuu-1111-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    interactive = MagicMock()
    interactive.upload = AsyncMock(return_value=MagicMock())
    fake_client.interact_session = AsyncMock(return_value=interactive)

    payload = b"hello sliver"
    r = client.post(
        f"/api/implants/{sid}/upload",
        files={"file": ("note.txt", payload, "application/octet-stream")},
        data={"dest_path": "C:\\Users\\user\\AppData\\Local\\Temp\\note.txt"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "session"
    assert body["bytes_written"] == len(payload)
    assert body["dest_path"].endswith("note.txt")
    interactive.upload.assert_awaited_once()
    args, _ = interactive.upload.call_args
    assert args[0].endswith("note.txt")
    assert args[1] == payload


def test_upload_on_beacon_returns_task_id(client, fake_client):
    bid = "uuuuuuuu-2222-2222-2222-222222222222"
    fake_client.beacons.return_value = [_FakeImplant(bid)]
    interactive = MagicMock()
    interactive.beacon_tasks = {}
    interactive.timeout = 30
    interactive._request = lambda pb: pb
    # Beacon's upload would return an asyncio.Future via @beacon_taskresult;
    # we just need it to be awaitable so _run_beacon_task's runner can spawn.
    async def fake_upload(_path, _data):
        import asyncio
        return asyncio.Future()
    interactive.upload = fake_upload
    fake_client.interact_beacon = AsyncMock(return_value=interactive)

    r = client.post(
        f"/api/implants/{bid}/upload",
        files={"file": ("a.bin", b"x" * 4096, "application/octet-stream")},
        data={"dest_path": "C:\\tmp\\a.bin"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "beacon"
    assert "task_id" in body and "queued_at" in body


def test_upload_oversized_returns_413(client, fake_client):
    sid = "uuuuuuuu-3333-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    # 101 MB → exceeds the 100 MB cap.
    big = b"\x00" * (101 * 1024 * 1024)
    r = client.post(
        f"/api/implants/{sid}/upload",
        files={"file": ("big.bin", big, "application/octet-stream")},
        data={"dest_path": "/tmp/big.bin"},
    )
    assert r.status_code == 413
    assert "too large" in r.json()["detail"].lower()


def test_upload_relative_path_returns_400(client, fake_client):
    sid = "uuuuuuuu-4444-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    r = client.post(
        f"/api/implants/{sid}/upload",
        files={"file": ("a.txt", b"abc", "text/plain")},
        data={"dest_path": "relative/path/file.txt"},
    )
    assert r.status_code == 400
    assert "must be absolute" in r.json()["detail"].lower()


def test_upload_missing_dest_path_returns_400(client, fake_client):
    sid = "uuuuuuuu-5555-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    # Empty string still triggers our "required" check (FastAPI accepts the
    # field, our handler rejects it with a clear message).
    r = client.post(
        f"/api/implants/{sid}/upload",
        files={"file": ("a.txt", b"abc", "text/plain")},
        data={"dest_path": ""},
    )
    assert r.status_code == 400


def test_upload_missing_file_returns_400(client, fake_client):
    sid = "uuuuuuuu-6666-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    # Omitting `file` entirely → FastAPI's own 422 (Form/File validation
    # failure). The handler never runs, so we accept the 4xx-class status.
    r = client.post(
        f"/api/implants/{sid}/upload",
        data={"dest_path": "/tmp/x"},
    )
    assert 400 <= r.status_code < 500


def test_upload_unknown_implant_returns_404(client, fake_client):
    fake_client.sessions.return_value = []
    fake_client.beacons.return_value = []
    r = client.post(
        "/api/implants/nope/upload",
        files={"file": ("a.txt", b"abc", "text/plain")},
        data={"dest_path": "/tmp/x.txt"},
    )
    assert r.status_code == 404


def test_sessions_exec_alias_still_works(client, fake_client):
    """The old /api/sessions/{id}/exec must still return ExecResponse shape."""
    sid = "dddddddd-1111-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    interactive = MagicMock()
    interactive.execute = AsyncMock(return_value=_ExecRes(stdout=b"hello\n"))
    fake_client.interact_session = AsyncMock(return_value=interactive)

    r = client.post(f"/api/sessions/{sid}/exec",
                    json={"cmd": "whoami", "args": [], "timeout": 30, "output": True})
    assert r.status_code == 200
    body = r.json()
    # Old shape: stdout/stderr/status/pid
    assert body["stdout"].startswith("hello")
    assert body["status"] == 0
    assert "pid" in body
