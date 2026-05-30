"""Task endpoint tests — status lookup, file-typed result streaming."""
from __future__ import annotations

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


def test_unknown_task_404(client):
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.get("/api/tasks/nope/result").status_code == 404


def test_complete_task_with_file_result_streams(client):
    from task_registry import registry
    rec = registry.create("screenshot", "implant-1", "session")
    png = b"\x89PNG\r\n\x1a\nFAKE"
    registry.set_complete(
        rec.task_id, result={"size": len(png)},
        result_kind="screenshot",
        result_bytes=png,
        result_mime="image/png",
        result_filename="shot.png",
    )

    s = client.get(f"/api/tasks/{rec.task_id}").json()
    assert s["state"] == "complete"
    assert s["result_kind"] == "screenshot"

    r = client.get(f"/api/tasks/{rec.task_id}/result")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == png


def test_running_task_result_returns_409(client):
    from task_registry import registry
    rec = registry.create("exec", "implant-1", "beacon")
    registry.set_running(rec.task_id)
    r = client.get(f"/api/tasks/{rec.task_id}/result")
    assert r.status_code == 409


def test_text_task_result_endpoint_404s_for_bytes(client):
    """Text-only results have no bytes; /result must 404 with a clear msg."""
    from task_registry import registry
    rec = registry.create("exec", "implant-2", "beacon")
    registry.set_complete(rec.task_id, result={"stdout": "hi", "stderr": "", "exit_code": 0},
                          result_kind="exec")
    r = client.get(f"/api/tasks/{rec.task_id}/result")
    assert r.status_code == 404
