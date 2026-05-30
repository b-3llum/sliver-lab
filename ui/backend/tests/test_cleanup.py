"""Phase 6b — bulk-forget orphan listeners + dead/stale beacons.

Listener bulk-delete runs against a hermetic temp sliver.db; beacon tests
mock the sliver-py client (kill_beacon → RmBeacon RPC).
"""
from __future__ import annotations

import sqlite3
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_INTERVAL_NS = 60 * 10**9  # 60s in nanoseconds


class _FakeBeacon:
    def __init__(self, ID: str, next_checkin: int, interval_ns: int = _INTERVAL_NS):
        self.ID = ID
        self.Name = "B"
        self.Hostname = "win10-sandbox"
        self.Username = "user"
        self.OS = "windows"
        self.Arch = "amd64"
        self.Transport = "mtls"
        self.RemoteAddress = "10.1.0.7:1000"
        self.PID = 5788
        self.NextCheckin = next_checkin
        self.Interval = interval_ns
        self.Jitter = 0
        self.TasksCount = 0
        self.TasksCountCompleted = 0


@pytest.fixture
def fake_client():
    c = MagicMock()
    c.sessions = AsyncMock(return_value=[])
    c.beacons = AsyncMock(return_value=[])
    c.jobs = AsyncMock(return_value=[])
    c.kill_beacon = AsyncMock(return_value=None)
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
    monkeypatch.setattr("routes.beacons._pb_to_dict", fake_pb)

    import main
    with TestClient(main.app) as c:
        yield c


# ── Listeners: bulk forget ─────────────────────────────────────────

def _seed_three_orphans(db: Path) -> None:
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE listener_jobs (id uuid PRIMARY KEY, created_at datetime, job_id integer UNIQUE, type text);
            CREATE TABLE mtls_listeners (id uuid PRIMARY KEY, listener_job_id uuid, host text, port integer);
            CREATE TABLE http_listeners (id uuid PRIMARY KEY, listener_job_id uuid, host text, port integer);
            CREATE TABLE dns_listeners (id uuid PRIMARY KEY, listener_job_id uuid, canaries numeric, host text, port integer);
            CREATE TABLE wg_listeners (id uuid PRIMARY KEY, listener_job_id uuid, host text, port integer);
            CREATE TABLE multiplayer_listeners (id uuid PRIMARY KEY, listener_job_id uuid, host text, port integer);
        """)
        for job_id, port in [(1, 80), (2, 8080), (3, 9090)]:
            lid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO listener_jobs (id, created_at, job_id, type) VALUES (?, ?, ?, ?)",
                (lid, "2026-01-01 00:00:00", job_id, "http"),
            )
            conn.execute(
                "INSERT INTO http_listeners (id, listener_job_id, host, port) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), lid, "0.0.0.0", port),
            )


def test_bulk_forget_persistent_clears_all(client, monkeypatch, tmp_path):
    db = tmp_path / "sliver.db"
    _seed_three_orphans(db)
    from routes import listeners as listeners_mod
    monkeypatch.setattr(listeners_mod, "SLIVER_DB_PATH", db)

    r = client.delete("/api/listeners/persistent")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 3
    assert body["errors"] == []

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM listener_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM http_listeners").fetchone()[0] == 0


def test_bulk_forget_persistent_missing_db_503(client, monkeypatch, tmp_path):
    from routes import listeners as listeners_mod
    monkeypatch.setattr(listeners_mod, "SLIVER_DB_PATH", tmp_path / "nope.db")
    assert client.delete("/api/listeners/persistent").status_code == 503


def test_bulk_forget_persistent_empty_db(client, monkeypatch, tmp_path):
    db = tmp_path / "sliver.db"
    # Schema present but no rows.
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE listener_jobs (id uuid PRIMARY KEY, created_at datetime, job_id integer UNIQUE, type text);
            CREATE TABLE http_listeners (id uuid PRIMARY KEY, listener_job_id uuid, host text, port integer);
        """)
    from routes import listeners as listeners_mod
    monkeypatch.setattr(listeners_mod, "SLIVER_DB_PATH", db)
    r = client.delete("/api/listeners/persistent")
    assert r.status_code == 200
    assert r.json() == {"deleted_count": 0, "errors": []}


# ── Beacons: stale field + forget ──────────────────────────────────

def test_beacons_stale_field(client, fake_client):
    now = int(time.time())
    fake_client.beacons.return_value = [
        _FakeBeacon("stale-1", next_checkin=now - 10_000),  # overdue ≫ 2×interval
        _FakeBeacon("fresh-1", next_checkin=now + 1_000),
    ]
    r = client.get("/api/beacons")
    assert r.status_code == 200
    by_id = {b["ID"]: b for b in r.json()}
    assert by_id["stale-1"]["stale"] is True
    assert by_id["fresh-1"]["stale"] is False


def test_forget_beacon_happy(client, fake_client):
    now = int(time.time())
    fake_client.beacons.return_value = [_FakeBeacon("kill-me", next_checkin=now - 10_000)]
    r = client.delete("/api/beacons/kill-me")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    fake_client.kill_beacon.assert_awaited_once_with("kill-me")


def test_forget_beacon_unknown_404(client, fake_client):
    fake_client.beacons.return_value = []
    r = client.delete("/api/beacons/nope")
    assert r.status_code == 404
    fake_client.kill_beacon.assert_not_awaited()


def test_forget_stale_beacons_bulk(client, fake_client):
    now = int(time.time())
    fake_client.beacons.return_value = [
        _FakeBeacon("s1", next_checkin=now - 10_000),
        _FakeBeacon("s2", next_checkin=now - 10_000),
        _FakeBeacon("f1", next_checkin=now + 1_000),
    ]
    r = client.delete("/api/beacons/stale")
    assert r.status_code == 200
    assert r.json() == {"deleted_count": 2}
    killed = {c.args[0] for c in fake_client.kill_beacon.await_args_list}
    assert killed == {"s1", "s2"}


def test_forget_stale_beacons_none(client, fake_client):
    now = int(time.time())
    fake_client.beacons.return_value = [_FakeBeacon("f1", next_checkin=now + 1_000)]
    r = client.delete("/api/beacons/stale")
    assert r.status_code == 200
    assert r.json() == {"deleted_count": 0}
    fake_client.kill_beacon.assert_not_awaited()
