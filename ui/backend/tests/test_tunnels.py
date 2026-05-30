"""Tunnel registry + route tests.

We never spawn sliver-client. Instead we stub
`asyncio.create_subprocess_exec` to return a fake process whose stdout
feeds the expected success marker, then assert the registry/route
behaviour around it.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── fixtures ───────────────────────────────────────────────────────


class _FakeImplant:
    def __init__(self, ID: str):
        self.ID = ID
        self.Name = "X"; self.Hostname = "winbox"; self.Username = "user"
        self.OS = "windows"; self.Arch = "amd64"; self.Transport = "mtls"
        self.RemoteAddress = "10.1.0.7:1000"; self.Pid = 100
        self.UID = "0"; self.GID = "0"
        self.LastCheckin = 0; self.IsDead = False; self.Filename = ""
        self.ActiveC2 = ""
        self.NextCheckin = 0; self.Interval = 60; self.Jitter = 10
        self.TasksCount = 0; self.TasksCountCompleted = 0


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
    import main
    # Each test gets a clean registry — make sure no entries from prior tests
    # leak across.
    from tunnel_registry import tunnel_registry
    tunnel_registry._tunnels.clear()
    with TestClient(main.app) as c:
        yield c


# ── fake subprocess plumbing ───────────────────────────────────────


_fake_procs: dict[int, MagicMock] = {}


def _fake_proc(stdout_lines: list[bytes]):
    """A MagicMock pretending to be an asyncio subprocess. Stdout yields
    the supplied lines, then blocks until the test triggers SIGTERM via
    the patched os.killpg below."""
    proc = MagicMock()
    pid = 10000 + len(_fake_procs)
    proc.pid = pid
    proc.returncode = None
    proc._exit_evt = asyncio.Event()

    iter_lines = iter(stdout_lines)
    async def read(_n):
        try:
            return next(iter_lines)
        except StopIteration:
            await proc._exit_evt.wait()
            return b""
    proc.stdout = MagicMock()
    proc.stdout.read = read

    async def wait():
        await proc._exit_evt.wait()
        return proc.returncode
    proc.wait = wait

    _fake_procs[pid] = proc
    return proc


def _patch_spawn(monkeypatch, proc_factory):
    """Patch the spawn + killpg pair. killpg sets the matching proc's
    returncode and triggers its exit-event so close_all completes quickly."""
    _fake_procs.clear()

    async def fake_create(*_args, **_kwargs):
        return proc_factory()
    monkeypatch.setattr(
        "tunnel_registry.asyncio.create_subprocess_exec", fake_create,
    )

    def fake_killpg(pgid, _sig):
        proc = _fake_procs.get(pgid)
        if proc is not None:
            proc.returncode = 0
            proc._exit_evt.set()
    monkeypatch.setattr("tunnel_registry.os.killpg", fake_killpg)
    monkeypatch.setattr("tunnel_registry.os.getpgid", lambda pid: pid)


def _patch_unlink_rc(monkeypatch):
    # Accept any args — when patched as a class attr the call passes `self`
    # plus the path, so we need a variadic stub.
    monkeypatch.setattr(
        "tunnel_registry.TunnelRegistry._unlink_rc", lambda *_a, **_kw: None,
    )


# ── happy paths ────────────────────────────────────────────────────


_SID = "session-aaaaaaaaaaaa"


def test_list_empty_for_session(client, fake_client):
    fake_client.sessions.return_value = [_FakeImplant(_SID)]
    body = client.get(f"/api/implants/{_SID}/tunnels").json()
    assert body == {"portfwds": [], "rportfwds": [], "socks5": []}


def test_create_portfwd_happy(client, fake_client, monkeypatch):
    fake_client.sessions.return_value = [_FakeImplant(_SID)]
    _patch_unlink_rc(monkeypatch)
    _patch_spawn(monkeypatch, lambda: _fake_proc([
        b"Connecting...\n",
        b"[*] Active session\n",
        b"[*] Port forwarding 127.0.0.1:9999 -> 127.0.0.1:80\n",
    ]))

    r = client.post(
        f"/api/implants/{_SID}/portfwd",
        json={"bind_addr": "127.0.0.1", "bind_port": 9999,
              "remote_addr": "127.0.0.1", "remote_port": 80},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "portfwd"
    assert body["marker_seen"] is True
    assert body["bind_port"] == 9999
    assert body["remote_port"] == 80
    assert "id" in body and "started_at" in body

    # list reflects it
    listing = client.get(f"/api/implants/{_SID}/tunnels").json()
    assert len(listing["portfwds"]) == 1
    assert listing["portfwds"][0]["id"] == body["id"]


def test_create_rportfwd_happy(client, fake_client, monkeypatch):
    fake_client.sessions.return_value = [_FakeImplant(_SID)]
    _patch_unlink_rc(monkeypatch)
    _patch_spawn(monkeypatch, lambda: _fake_proc([
        b"[*] Reverse port forwarding 127.0.0.1:80 <- 0.0.0.0:5555\n",
    ]))
    r = client.post(
        f"/api/implants/{_SID}/rportfwd",
        json={"bind_addr": "0.0.0.0", "bind_port": 5555,
              "remote_addr": "127.0.0.1", "remote_port": 80},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "rportfwd"


def test_create_socks5_happy(client, fake_client, monkeypatch):
    fake_client.sessions.return_value = [_FakeImplant(_SID)]
    _patch_unlink_rc(monkeypatch)
    _patch_spawn(monkeypatch, lambda: _fake_proc([
        b"[*] Started SOCKS5 127.0.0.1 1080\n",
    ]))
    r = client.post(
        f"/api/implants/{_SID}/socks5",
        json={"bind_addr": "127.0.0.1", "bind_port": 1080},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "socks5"
    assert body["remote_port"] == 0
    assert body["remote_addr"] == ""


# ── delete ─────────────────────────────────────────────────────────


def test_delete_removes_tunnel(client, fake_client, monkeypatch):
    fake_client.sessions.return_value = [_FakeImplant(_SID)]
    _patch_unlink_rc(monkeypatch)
    _patch_spawn(monkeypatch, lambda: _fake_proc([
        b"[*] Port forwarding 127.0.0.1:9999 -> 127.0.0.1:80\n",
    ]))
    created = client.post(
        f"/api/implants/{_SID}/portfwd",
        json={"bind_addr": "127.0.0.1", "bind_port": 9999,
              "remote_addr": "127.0.0.1", "remote_port": 80},
    ).json()
    tid = created["id"]
    r = client.delete(f"/api/implants/{_SID}/portfwd/{tid}")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert client.get(f"/api/implants/{_SID}/tunnels").json()["portfwds"] == []


def test_delete_unknown_tunnel_404(client, fake_client):
    fake_client.sessions.return_value = [_FakeImplant(_SID)]
    assert client.delete(f"/api/implants/{_SID}/portfwd/no-such").status_code == 404


# ── negatives ──────────────────────────────────────────────────────


def test_duplicate_bind_409(client, fake_client, monkeypatch):
    fake_client.sessions.return_value = [_FakeImplant(_SID)]
    _patch_unlink_rc(monkeypatch)
    _patch_spawn(monkeypatch, lambda: _fake_proc([
        b"[*] Port forwarding 127.0.0.1:9999 -> 127.0.0.1:80\n",
    ]))
    body = {"bind_addr": "127.0.0.1", "bind_port": 9999,
            "remote_addr": "127.0.0.1", "remote_port": 80}
    assert client.post(f"/api/implants/{_SID}/portfwd", json=body).status_code == 200
    r = client.post(f"/api/implants/{_SID}/portfwd", json=body)
    assert r.status_code == 409
    assert "already bound" in r.json()["detail"].lower()


def test_beacon_returns_400(client, fake_client):
    bid = "beacon-bbbbbbbbbbbb"
    fake_client.beacons.return_value = [_FakeImplant(bid)]
    fake_client.sessions.return_value = []
    r = client.post(
        f"/api/implants/{bid}/portfwd",
        json={"bind_addr": "127.0.0.1", "bind_port": 9999,
              "remote_addr": "127.0.0.1", "remote_port": 80},
    )
    assert r.status_code == 400
    assert "promote" in r.json()["detail"].lower()


def test_unknown_implant_id_404(client, fake_client):
    fake_client.sessions.return_value = []
    fake_client.beacons.return_value = []
    for path in (
        "/api/implants/nope/tunnels",
        "/api/implants/nope/portfwd",
        "/api/implants/nope/socks5",
    ):
        if path.endswith("/tunnels"):
            r = client.get(path)
        elif path.endswith("/socks5"):
            r = client.post(path, json={"bind_addr": "127.0.0.1", "bind_port": 1080})
        else:
            r = client.post(path, json={
                "bind_addr": "127.0.0.1", "bind_port": 9999,
                "remote_addr": "127.0.0.1", "remote_port": 80})
        assert r.status_code == 404, path


def test_invalid_port_400(client, fake_client):
    fake_client.sessions.return_value = [_FakeImplant(_SID)]
    r = client.post(
        f"/api/implants/{_SID}/portfwd",
        json={"bind_addr": "127.0.0.1", "bind_port": 0,
              "remote_addr": "127.0.0.1", "remote_port": 80},
    )
    assert r.status_code == 400


def test_invalid_bind_addr_400(client, fake_client):
    fake_client.sessions.return_value = [_FakeImplant(_SID)]
    r = client.post(
        f"/api/implants/{_SID}/socks5",
        json={"bind_addr": "not-an-ip", "bind_port": 1080},
    )
    assert r.status_code == 400


# ── orphan reaper ──────────────────────────────────────────────────


def test_orphan_reaper_invokes_pgrep_and_kill(monkeypatch):
    """Mock both subprocess.run (pgrep) and os.kill, assert both fire."""
    import tunnel_registry as tr
    killed_pids: list[int] = []

    def fake_run(_argv, **_kwargs):
        return MagicMock(stdout="111\n222\n", returncode=0)

    def fake_kill(pid, sig):
        killed_pids.append(pid)

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    monkeypatch.setattr(tr.os, "kill", fake_kill)
    n = tr.reap_orphans()
    assert n == 2
    assert sorted(killed_pids) == [111, 222]


def test_orphan_reaper_swallows_pgrep_failure(monkeypatch):
    import tunnel_registry as tr

    def fake_run(*_a, **_kw):
        raise RuntimeError("pgrep blew up")
    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    # Doesn't raise, returns 0.
    assert tr.reap_orphans() == 0
