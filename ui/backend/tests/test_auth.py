"""Phase 7a — single-token auth on the BFF.

The autouse conftest fixture pins SLIVER_UI_TOKEN=TEST_TOKEN and gives every
TestClient a default `Authorization: Bearer <TEST_TOKEN>` header. These tests
opt out of that header where they need to probe the unauthenticated paths.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import TEST_TOKEN  # noqa: E402


@pytest.fixture
def app_client(monkeypatch):
    from sliver_client import hub
    fake = MagicMock()
    fake.sessions = AsyncMock(return_value=[])
    monkeypatch.setattr(type(hub), "client", property(lambda self: fake))
    monkeypatch.setattr(hub, "_connected", True)
    import main
    with TestClient(main.app) as c:
        yield c


# ── HTTP gate ──────────────────────────────────────────────────────

def test_missing_authorization_header_401(app_client):
    app_client.headers.pop("Authorization", None)
    r = app_client.get("/api/sessions")
    assert r.status_code == 401
    assert r.json()["detail"] == "unauthorized — paste the UI token"


def test_wrong_token_401(app_client):
    app_client.headers["Authorization"] = "Bearer not-the-real-token"
    r = app_client.get("/api/sessions")
    assert r.status_code == 401


def test_correct_token_200(app_client):
    # Default header (from conftest) is the correct token.
    r = app_client.get("/api/sessions")
    assert r.status_code == 200
    assert r.json() == []


def test_health_works_without_token(app_client):
    app_client.headers.pop("Authorization", None)
    r = app_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_query_param_token_authorizes_http(app_client):
    # img/<a> result GETs can't send a header — the ?token= path must work too.
    app_client.headers.pop("Authorization", None)
    r = app_client.get(f"/api/sessions?token={TEST_TOKEN}")
    assert r.status_code == 200


# ── WebSocket gate ─────────────────────────────────────────────────

def test_ws_without_token_closes_1008(app_client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with app_client.websocket_connect("/events") as ws:
            ws.receive_json()  # server accepted then closed with 1008
    assert exc.value.code == 1008


def test_ws_wrong_token_closes_1008(app_client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with app_client.websocket_connect("/events?token=bogus") as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_ws_correct_token_connects(app_client):
    with app_client.websocket_connect(f"/events?token={TEST_TOKEN}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "bff:state"


# ── Token resolution ───────────────────────────────────────────────

def test_token_from_env_used_verbatim(monkeypatch):
    monkeypatch.setenv("SLIVER_UI_TOKEN", "my-fixed-token-xyz")
    import auth
    assert auth.load_or_generate_token() == "my-fixed-token-xyz"
    assert auth.current_token() == "my-fixed-token-xyz"


def test_token_generated_and_logged_when_env_unset(monkeypatch, caplog):
    monkeypatch.delenv("SLIVER_UI_TOKEN", raising=False)
    import auth
    with caplog.at_level(logging.WARNING, logger="sliverui.auth"):
        tok = auth.load_or_generate_token()
    assert tok and len(tok) >= 20
    assert any("UI auth token:" in r.getMessage() for r in caplog.records)
