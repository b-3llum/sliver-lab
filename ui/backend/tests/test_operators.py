"""Phase 7c — multi-operator awareness."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _FakeOperator:
    def __init__(self, name: str, online: bool):
        self.Name = name
        self.Online = online


@pytest.fixture
def fake_client():
    c = MagicMock()
    c.operators = AsyncMock(return_value=[])
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
    monkeypatch.setattr("routes.operators._pb_to_dict", fake_pb)

    import main
    with TestClient(main.app) as c:
        yield c


def test_operators_happy_path(client, fake_client):
    fake_client.operators.return_value = [
        _FakeOperator("bellum", True),
        _FakeOperator("teammate", False),
    ]
    r = client.get("/api/operators")
    assert r.status_code == 200
    body = r.json()
    assert body == [
        {"name": "bellum", "online": True},
        {"name": "teammate", "online": False},
    ]


def test_operators_empty(client, fake_client):
    fake_client.operators.return_value = []
    r = client.get("/api/operators")
    assert r.status_code == 200
    assert r.json() == []


def test_operators_requires_auth(client):
    client.headers.pop("Authorization", None)
    r = client.get("/api/operators")
    assert r.status_code == 401


def test_operator_me_uses_env_override(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_NAME", "bellum")
    r = client.get("/api/operators/me")
    assert r.status_code == 200
    assert r.json() == {"name": "bellum"}


def test_operator_me_falls_back_to_config(client, monkeypatch):
    monkeypatch.delenv("OPERATOR_NAME", raising=False)
    # Stub the config parse so the test doesn't depend on a real .cfg file.
    fake_cfg = MagicMock()
    fake_cfg.operator = "config-operator"
    import sliver
    monkeypatch.setattr(sliver.SliverClientConfig, "parse_config_file",
                        staticmethod(lambda _p: fake_cfg))
    r = client.get("/api/operators/me")
    assert r.status_code == 200
    assert r.json() == {"name": "config-operator"}
