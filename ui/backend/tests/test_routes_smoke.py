"""Smoke tests — one per route group, plus targeted tests for the listener
filter and the persistent-listener sqlite escape hatch.

We stub the Sliver hub so tests run without a teamserver, and we point the
backend at a temp sliver.db so the persistent tests work hermetically.
"""
from __future__ import annotations

import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def fake_client():
    """A MagicMock standing in for the sliver-py client. Tests can override
    individual methods (e.g. .jobs.return_value) to feed specific data."""
    c = MagicMock()
    c.sessions = AsyncMock(return_value=[])
    c.beacons = AsyncMock(return_value=[])
    c.jobs = AsyncMock(return_value=[])
    c.loot_all = AsyncMock(return_value=[])
    c.kill_job = AsyncMock(return_value=None)
    return c


@pytest.fixture
def client(monkeypatch, fake_client):
    from sliver_client import hub
    monkeypatch.setattr(type(hub), "client", property(lambda self: fake_client))
    monkeypatch.setattr(hub, "_connected", True)
    import main
    with TestClient(main.app) as c:
        yield c


# ── basic shape ─────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_sessions_empty(client):
    assert client.get("/api/sessions").json() == []


def test_beacons_empty(client):
    assert client.get("/api/beacons").json() == []


def test_jobs_empty(client):
    assert client.get("/api/jobs").json() == []


def test_listeners_empty(client):
    assert client.get("/api/listeners").json() == []


def test_loot_empty(client):
    assert client.get("/api/loot").json() == []


# ── build (avgen) ───────────────────────────────────────────────────

def test_build_options_returns_schema(client):
    r = client.get("/api/build/options")
    assert r.status_code == 200
    body = r.json()
    assert "avgen_path" in body and "avgen_present" in body and "groups" in body


# ── bofs ────────────────────────────────────────────────────────────

def test_bofs_library_missing_dir(client, monkeypatch, tmp_path):
    monkeypatch.setenv("BOF_DIR", str(tmp_path / "does-not-exist"))
    info = client.get("/api/bofs/library").json()
    assert info["env_set"] is True
    assert info["exists"] is False
    assert info["count"] == 0
    assert client.get("/api/bofs").json() == []


def test_bofs_dir_scan(client, monkeypatch, tmp_path):
    (tmp_path / "credential-access").mkdir()
    (tmp_path / "credential-access" / "mimikatz.x64.o").write_bytes(b"\x7fELF")
    (tmp_path / "loose.o").write_bytes(b"\x7fELF")
    monkeypatch.setenv("BOF_DIR", str(tmp_path))
    bofs = client.get("/api/bofs").json()
    names = {b["name"]: b for b in bofs}
    assert "mimikatz.x64" in names
    assert names["mimikatz.x64"]["category"] == "credential-access"
    assert names["mimikatz.x64"]["available"] is True
    assert "loose" in names
    assert names["loose"]["category"] == "uncategorized"


def test_bof_build_command_for_missing(client, monkeypatch, tmp_path):
    monkeypatch.setenv("BOF_DIR", str(tmp_path))
    r = client.post("/api/bofs/does-not-exist/build_command", params={"session_id": "x"})
    assert r.status_code == 404


# ── profiles ────────────────────────────────────────────────────────

def test_profiles_presets_returns_curated(client):
    r = client.get("/api/profiles/presets")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    assert {"amazon-cloudfront", "windows-update", "generic-cdn"} <= names


# ── listener filter: name-based, not protocol-based ────────────────

class _FakeJob:
    """Mimics a sliver-py protobuf Job for _pb_to_dict purposes."""
    def __init__(self, ID: int, name: str, protocol: str, port: int, description: str = ""):
        self.ID = ID
        self.Name = name
        self.Protocol = protocol
        self.Port = port
        self.Description = description


def test_listener_filter_includes_mtls_by_name(client, monkeypatch, fake_client):
    """The bug we're regression-testing: Sliver's Job.Name carries the kind
    ("mtls"), Job.Protocol carries the wire layer ("tcp"). The filter must
    match on Name, not Protocol."""
    from routes import listeners as listeners_mod
    fake_job = _FakeJob(ID=7, name="mtls", protocol="tcp", port=8443, description="mTLS listener")
    fake_client.jobs.return_value = [fake_job]
    monkeypatch.setattr(listeners_mod, "_pb_to_dict", lambda m: (
        {"ID": m.ID, "Name": m.Name, "Protocol": m.Protocol, "Port": m.Port,
         "Description": m.Description} if isinstance(m, _FakeJob) else None
    ))
    r = client.get("/api/listeners")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "mtls"
    assert body[0]["protocol"] == "tcp"
    assert body[0]["port"] == 8443


def test_listener_filter_excludes_non_listener_jobs(client, monkeypatch, fake_client):
    from routes import listeners as listeners_mod
    portfwd = _FakeJob(ID=42, name="portfwd", protocol="tcp", port=4444)
    fake_client.jobs.return_value = [portfwd]
    monkeypatch.setattr(listeners_mod, "_pb_to_dict", lambda m: (
        {"ID": m.ID, "Name": m.Name, "Protocol": m.Protocol, "Port": m.Port,
         "Description": m.Description} if isinstance(m, _FakeJob) else None
    ))
    assert client.get("/api/listeners").json() == []


# ── persistent-listener escape hatch (sqlite) ───────────────────────

def _make_fake_sliver_db(path: Path) -> tuple[int, str]:
    """Create a sliver.db with one orphan mtls listener. Returns (job_id, uuid)."""
    listener_uuid = str(uuid.uuid4())
    job_id = 99
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE listener_jobs (id uuid PRIMARY KEY, created_at datetime, job_id integer UNIQUE, type text);
            CREATE TABLE mtls_listeners (id uuid PRIMARY KEY, listener_job_id uuid, host text, port integer);
            CREATE TABLE http_listeners (id uuid PRIMARY KEY, listener_job_id uuid, host text, port integer);
            CREATE TABLE dns_listeners (id uuid PRIMARY KEY, listener_job_id uuid, canaries numeric, host text, port integer);
            CREATE TABLE wg_listeners (id uuid PRIMARY KEY, listener_job_id uuid, host text, port integer);
            CREATE TABLE multiplayer_listeners (id uuid PRIMARY KEY, listener_job_id uuid, host text, port integer);
        """)
        conn.execute(
            "INSERT INTO listener_jobs (id, created_at, job_id, type) VALUES (?, ?, ?, ?)",
            (listener_uuid, "2026-01-01 00:00:00", job_id, "mtls"),
        )
        conn.execute(
            "INSERT INTO mtls_listeners (id, listener_job_id, host, port) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), listener_uuid, "0.0.0.0", 8443),
        )
    return job_id, listener_uuid


def test_persistent_list_then_forget(client, monkeypatch, tmp_path):
    db = tmp_path / "sliver.db"
    job_id, _ = _make_fake_sliver_db(db)
    # Repoint the route's module-level SLIVER_DB_PATH so the request reads
    # the temp db. We patch the module attr because the route reads it eagerly.
    from routes import listeners as listeners_mod
    monkeypatch.setattr(listeners_mod, "SLIVER_DB_PATH", db)

    rows = client.get("/api/listeners/persistent").json()
    assert len(rows) == 1
    assert rows[0]["job_id"] == job_id
    assert rows[0]["kind"] == "mtls"
    assert rows[0]["port"] == 8443

    r = client.delete(f"/api/listeners/persistent/{job_id}")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Row is gone in both tables.
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM listener_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mtls_listeners").fetchone()[0] == 0


def test_persistent_forget_404_on_missing(client, monkeypatch, tmp_path):
    db = tmp_path / "sliver.db"
    _make_fake_sliver_db(db)
    from routes import listeners as listeners_mod
    monkeypatch.setattr(listeners_mod, "SLIVER_DB_PATH", db)
    assert client.delete("/api/listeners/persistent/9999").status_code == 404


def test_persistent_missing_db_returns_503(client, monkeypatch, tmp_path):
    from routes import listeners as listeners_mod
    monkeypatch.setattr(listeners_mod, "SLIVER_DB_PATH", tmp_path / "nope.db")
    assert client.get("/api/listeners/persistent").status_code == 503


# ── persistent endpoint must hide currently-running jobs ────────────

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
        for job_id, port in [(100, 8001), (101, 8002), (102, 8003)]:
            lid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO listener_jobs (id, created_at, job_id, type) VALUES (?, ?, ?, ?)",
                (lid, "2026-01-01 00:00:00", job_id, "mtls"),
            )
            conn.execute(
                "INSERT INTO mtls_listeners (id, listener_job_id, host, port) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), lid, "0.0.0.0", port),
            )


def test_persistent_excludes_live_job_ids(client, monkeypatch, fake_client, tmp_path):
    db = tmp_path / "sliver.db"
    _seed_three_orphans(db)
    from routes import listeners as listeners_mod
    monkeypatch.setattr(listeners_mod, "SLIVER_DB_PATH", db)
    # One of the seeded job_ids is also a live job — should be filtered out.
    fake_client.jobs.return_value = [_FakeJob(ID=101, name="mtls", protocol="tcp", port=8002)]
    monkeypatch.setattr(listeners_mod, "_pb_to_dict", lambda m: (
        {"ID": m.ID, "Name": m.Name, "Protocol": m.Protocol, "Port": m.Port,
         "Description": m.Description} if isinstance(m, _FakeJob) else None
    ))
    rows = client.get("/api/listeners/persistent").json()
    job_ids = sorted(r["job_id"] for r in rows)
    assert job_ids == [100, 102]


def test_persistent_falls_back_when_jobs_unavailable(client, monkeypatch, fake_client, tmp_path):
    db = tmp_path / "sliver.db"
    _seed_three_orphans(db)
    from routes import listeners as listeners_mod
    monkeypatch.setattr(listeners_mod, "SLIVER_DB_PATH", db)
    # Server is offline — jobs() blows up. We should still get all 3 rows.
    fake_client.jobs.side_effect = RuntimeError("sliver-server unreachable")
    rows = client.get("/api/listeners/persistent").json()
    assert sorted(r["job_id"] for r in rows) == [100, 101, 102]


# ── _parse_domains ──────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (None, []),
    ("", []),
    ("[]", []),
    ("[ ]", []),
    ("   ", []),
    ("[a.com]", ["a.com"]),
    ("[a.com b.com]", ["a.com", "b.com"]),
    ("[ a.com  b.com ]", ["a.com", "b.com"]),
    (["a.com", "b.com"], ["a.com", "b.com"]),
    (("a.com",), ["a.com"]),
    (["", "a.com", "  "], ["a.com"]),
    (42, []),  # pathological non-string scalar
])
def test_parse_domains(value, expected):
    from routes.listeners import _parse_domains
    assert _parse_domains(value) == expected
