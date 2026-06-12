"""Engagement-reporting layer — /api/report and /api/report/markdown.

Footholds come from a live teamserver; the test fixture has no real client, so
hub.client raises and _collect_footholds degrades to an empty list. These tests
exercise the audit-derived spine (timeline, technique counts, summary) and the
Markdown rendering, which is what the report logic owns.
"""
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


def _line(ts: str, user: str = "bellum", method: str = "/rpcpb.SliverRPC/Execute") -> str:
    msg = json.dumps({"request": "{}", "method": method, "remote_ip": "127.0.0.1:1", "user": user})
    return json.dumps({"level": "info", "msg": msg, "time": ts})


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _point_at(monkeypatch, path: Path) -> None:
    from routes import report as report_mod
    monkeypatch.setattr(report_mod, "AUDIT_LOG_PATH", path)


def test_report_builds_timeline_and_techniques(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    _write(db, [
        _line("2026-05-30T02:00:01-04:00", method="/rpcpb.SliverRPC/Execute"),
        _line("2026-05-30T02:00:02-04:00", method="/rpcpb.SliverRPC/Screenshot"),
        _line("2026-05-30T02:00:03-04:00", user="alice", method="/rpcpb.SliverRPC/Execute"),
    ])
    _point_at(monkeypatch, db)

    r = client.get("/api/report?engagement=Acme Q2").json()
    assert r["engagement"] == "Acme Q2"
    assert r["summary"]["operator_action_count"] == 3
    # operators preserved in first-seen (chronological) order
    assert r["summary"]["operators"] == ["bellum", "alice"]
    # Timeline is chronological (oldest first).
    assert [t["action"] for t in r["timeline"]] == ["Execute", "Screenshot", "Execute"]

    # Execute → T1059 (x2), Screenshot → T1113 (x1); sorted by count desc.
    techs = {t["id"]: t for t in r["techniques"]}
    assert techs["T1059"]["count"] == 2
    assert techs["T1059"]["tactic"] == "Execution"
    assert techs["T1113"]["count"] == 1
    assert r["summary"]["distinct_technique_count"] == 2
    assert r["techniques"][0]["id"] == "T1059"  # most frequent first


def test_unmapped_action_appears_untagged(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    _write(db, [_line("2026-05-30T02:00:01-04:00", method="/rpcpb.SliverRPC/SomeNovelRpc")])
    _point_at(monkeypatch, db)

    r = client.get("/api/report").json()
    assert r["engagement"] == "Untitled engagement"
    assert len(r["timeline"]) == 1
    assert r["timeline"][0]["action"] == "SomeNovelRpc"
    assert r["timeline"][0]["technique"] is None
    assert r["techniques"] == []


def test_polling_actions_excluded_by_default(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    _write(db, [
        _line("2026-05-30T02:00:01-04:00", method="/rpcpb.SliverRPC/GetSessions"),  # polling
        _line("2026-05-30T02:00:02-04:00", method="/rpcpb.SliverRPC/Execute"),
    ])
    _point_at(monkeypatch, db)

    assert client.get("/api/report").json()["summary"]["operator_action_count"] == 1
    assert client.get("/api/report?include_polling=true").json()["summary"]["operator_action_count"] == 2


def test_missing_audit_log_yields_empty_report(client, monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path / "nope.json")
    r = client.get("/api/report")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["operator_action_count"] == 0
    assert body["timeline"] == []
    assert body["footholds"] == []  # hub has no real client in tests


def test_markdown_download_headers_and_body(client, monkeypatch, tmp_path):
    db = tmp_path / "audit.json"
    _write(db, [_line("2026-05-30T02:00:01-04:00", method="/rpcpb.SliverRPC/Execute")])
    _point_at(monkeypatch, db)

    r = client.get("/api/report/markdown?engagement=Acme Q2")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.headers["content-disposition"] == 'attachment; filename="acme-q2-report.md"'
    body = r.text
    assert "# Engagement Report — Acme Q2" in body
    assert "## ATT&CK Techniques Observed" in body
    assert "T1059" in body
