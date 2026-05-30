"""Phase 7b — audit log tail surface."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client(monkeypatch):
    from sliver_client import hub
    monkeypatch.setattr(hub, "_connected", True)
    import main
    with TestClient(main.app) as c:
        yield c


def _line(ts: str, user: str = "bellum", method: str = "/rpcpb.SliverRPC/GetSessions") -> str:
    msg = json.dumps({"request": "{}", "method": method, "remote_ip": "127.0.0.1:1", "user": user})
    return json.dumps({"level": "info", "msg": msg, "time": ts})


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _point_at(monkeypatch, path: Path) -> None:
    from routes import audit as audit_mod
    monkeypatch.setattr(audit_mod, "AUDIT_LOG_PATH", path)


def test_tail_reads_most_recent_first(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    # 30 lines, increasing timestamps (00..29 seconds).
    lines = [_line(f"2026-05-30T02:00:{s:02d}-04:00", method=f"m{s}") for s in range(30)]
    _write(db, lines)
    _point_at(monkeypatch, db)

    body = client.get("/api/audit?limit=20").json()
    assert len(body["entries"]) == 20
    # Most-recent-first: first entry is the last line written (m29).
    assert body["entries"][0]["action"] == "m29"
    assert body["entries"][-1]["action"] == "m10"
    assert body["entries"][0]["operator"] == "bellum"
    # Nested msg fields land in details.
    assert body["entries"][0]["details"]["remote_ip"] == "127.0.0.1:1"


def test_since_filter_respects_timestamps(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    lines = [_line(f"2026-05-30T02:00:{s:02d}-04:00", method=f"m{s}") for s in range(10)]
    _write(db, lines)
    _point_at(monkeypatch, db)

    # since = the 5th second → only m5..m9 (>=) returned.
    body = client.get("/api/audit?since=2026-05-30T02:00:05-04:00").json()
    actions = {e["action"] for e in body["entries"]}
    assert actions == {"m5", "m6", "m7", "m8", "m9"}


def test_malformed_lines_skipped_not_500(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    good = _line("2026-05-30T02:00:01-04:00", method="ok1")
    good2 = _line("2026-05-30T02:00:03-04:00", method="ok2")
    _write(db, [good, "this is not json", "{broken", good2])
    _point_at(monkeypatch, db)

    r = client.get("/api/audit?limit=50")
    assert r.status_code == 200
    actions = {e["action"] for e in r.json()["entries"]}
    assert actions == {"ok1", "ok2"}


def test_missing_file_returns_empty_200(client, monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path / "does-not-exist.json")
    r = client.get("/api/audit")
    assert r.status_code == 200
    assert r.json() == {"entries": []}


def test_limit_clamped_to_5000(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    lines = [_line(f"2026-05-30T02:00:{s % 60:02d}-04:00", method=f"m{s}") for s in range(5100)]
    _write(db, lines)
    _point_at(monkeypatch, db)

    body = client.get("/api/audit?limit=99999").json()
    assert len(body["entries"]) == 5000


# ── F2: polling-action filter ──────────────────────────────────────

_GET = "/rpcpb.SliverRPC/GetSessions"      # default polling
_GETB = "/rpcpb.SliverRPC/GetBeacons"      # default polling
_REAL = "/rpcpb.SliverRPC/StartHTTPListener"
_KILL = "/rpcpb.SliverRPC/KillJob"


def test_polling_hidden_by_default(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    _write(db, [
        _line("2026-05-30T02:00:01-04:00", method=_GET),
        _line("2026-05-30T02:00:02-04:00", method=_REAL),
        _line("2026-05-30T02:00:03-04:00", method=_GETB),
        _line("2026-05-30T02:00:04-04:00", method=_KILL),
    ])
    _point_at(monkeypatch, db)
    actions = [e["action"] for e in client.get("/api/audit").json()["entries"]]
    # Only operator actions survive (newest-first); both polling RPCs gone.
    assert actions == [_KILL, _REAL]


def test_include_polling_shows_all(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    _write(db, [
        _line("2026-05-30T02:00:01-04:00", method=_GET),
        _line("2026-05-30T02:00:02-04:00", method=_REAL),
    ])
    _point_at(monkeypatch, db)
    assert len(client.get("/api/audit").json()["entries"]) == 1
    assert len(client.get("/api/audit?include_polling=true").json()["entries"]) == 2


def test_polling_actions_env_override(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    _write(db, [
        _line("2026-05-30T02:00:01-04:00", method=_GET),                       # default-polling
        _line("2026-05-30T02:00:02-04:00", method="/rpcpb.SliverRPC/CustomNoise"),
    ])
    _point_at(monkeypatch, db)
    monkeypatch.setenv("AUDIT_POLLING_ACTIONS", "CustomNoise")
    actions = [e["action"] for e in client.get("/api/audit").json()["entries"]]
    # The override replaces the default set: GetSessions now survives, CustomNoise is filtered.
    assert actions == [_GET]
