"""Phase E — ngrok public-exposure. The ngrok SDK is mocked at the module
boundary (ngrok_registry.ngrok) — no real tunnels, no network."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TUN_URL = "tcp://7.tcp.ngrok.io:18923"


# ── Fakes mirroring the REAL ngrok-python 1.7 async builder API ─────
# SessionBuilder().authtoken(t).connect() -> Session
# session.tcp_endpoint().listen_and_forward(url) -> Listener; listener.url()
# (NOT async_connect(addr, proto=…) — that was the bug.)

class _FakeListener:
    def __init__(self) -> None:
        self.closed = False

    def url(self) -> str:
        return TUN_URL

    async def close(self) -> None:
        self.closed = True


class _FakeTcpEndpoint:
    def __init__(self, sink, listener):
        self._sink = sink; self._listener = listener

    async def listen_and_forward(self, url=None):
        self._sink["forwarded"] = url
        return self._listener


class _FakeSession:
    def __init__(self, sink, listener):
        self._sink = sink; self._listener = listener; self.closed = False

    def tcp_endpoint(self):
        return _FakeTcpEndpoint(self._sink, self._listener)

    async def close(self) -> None:
        self.closed = True


class _FakeSessionBuilder:
    def __init__(self, sink):
        self._sink = sink

    def authtoken(self, token):
        self._sink["token"] = token
        return self

    async def connect(self):
        listener = _FakeListener()
        session = _FakeSession(self._sink, listener)
        self._sink["listener"] = listener
        self._sink["session"] = session
        return session


class _FakeNgrok:
    def __init__(self) -> None:
        self.killed = False
        self.sink: dict = {}

    def SessionBuilder(self):
        return _FakeSessionBuilder(self.sink)

    def kill(self) -> None:
        self.killed = True

    async def async_connect(self, config=None, **kw):
        # Trap: replicate the real binding so any regression to the old
        # `async_connect(addr, proto=…)` call blows up loudly in tests.
        if kw:
            raise TypeError(
                f"async_connect() got an unexpected keyword argument {next(iter(kw))!r}")
        raise AssertionError("registry must use the builder pattern, not async_connect()")


class _FakeJob:
    def __init__(self, ID, name, protocol, port):
        self.ID = ID; self.Name = name; self.Protocol = protocol
        self.Port = port; self.Description = ""; self.Domains = []


def _fake_pb(obj):
    if obj is None: return None
    if isinstance(obj, dict): return obj
    return {k: getattr(obj, k) for k in dir(obj)
            if not k.startswith("_") and not callable(getattr(obj, k, None))}


@pytest.fixture
def fake_ngrok(monkeypatch):
    import ngrok_registry
    fk = _FakeNgrok()
    monkeypatch.setattr(ngrok_registry, "ngrok", fk)
    ngrok_registry.registry._entries.clear()
    monkeypatch.setenv("NGROK_AUTHTOKEN", "test-token")
    yield fk
    ngrok_registry.registry._entries.clear()


# ── Registry-level ─────────────────────────────────────────────────

def test_registry_start_happy(fake_ngrok):
    from ngrok_registry import registry
    rec = asyncio.run(registry.start(8443))
    assert rec.listener_port == 8443
    assert rec.public_url == TUN_URL
    assert rec.public_host == "7.tcp.ngrok.io"
    assert rec.public_port == 18923
    assert rec.kind == "tcp"
    # Builder path: authtoken set, upstream forwarded as a tcp:// URL.
    assert fake_ngrok.sink["token"] == "test-token"
    assert fake_ngrok.sink["forwarded"] == "tcp://localhost:8443"


def test_registry_uses_builder_not_async_connect(fake_ngrok):
    """Regression guard for the SDK-signature bug: the registry must drive the
    builder pattern, never async_connect(addr, proto=…)."""
    from ngrok_registry import registry
    rec = asyncio.run(registry.start(8443))
    assert rec.public_url == TUN_URL
    assert fake_ngrok.sink["forwarded"] == "tcp://localhost:8443"
    # The old call shape raises against the real binding — confirm the trap.
    with pytest.raises(TypeError):
        asyncio.run(fake_ngrok.async_connect("localhost:8443", proto="tcp"))


def test_registry_duplicate(fake_ngrok):
    from ngrok_registry import registry, NgrokDuplicate
    asyncio.run(registry.start(8443))
    with pytest.raises(NgrokDuplicate):
        asyncio.run(registry.start(8443))


def test_registry_disabled_without_token(fake_ngrok, monkeypatch):
    from ngrok_registry import registry, NgrokDisabled
    monkeypatch.delenv("NGROK_AUTHTOKEN", raising=False)
    with pytest.raises(NgrokDisabled):
        asyncio.run(registry.start(8443))


def test_registry_stop(fake_ngrok):
    from ngrok_registry import registry
    rec = asyncio.run(registry.start(8443))
    asyncio.run(registry.stop(rec.id))
    assert registry.by_port(8443) is None
    # Both the listener and its session were closed.
    assert fake_ngrok.sink["listener"].closed is True
    assert fake_ngrok.sink["session"].closed is True


def test_registry_stop_unknown(fake_ngrok):
    from ngrok_registry import registry
    with pytest.raises(KeyError):
        asyncio.run(registry.stop("nope"))


def test_registry_close_all(fake_ngrok):
    from ngrok_registry import registry
    asyncio.run(registry.start(8443))
    asyncio.run(registry.close_all())
    assert registry.list() == []
    assert fake_ngrok.killed is True


# ── Route-level ────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, fake_ngrok):
    from sliver_client import hub
    fc = MagicMock()
    fc.jobs = AsyncMock(return_value=[_FakeJob("3", "mtls", "tcp", 8443)])
    fc.sessions = AsyncMock(return_value=[])
    fc.beacons = AsyncMock(return_value=[])
    monkeypatch.setattr(type(hub), "client", property(lambda self: fc))
    monkeypatch.setattr(hub, "_connected", True)
    monkeypatch.setattr("routes.listeners._pb_to_dict", _fake_pb)
    import main
    with TestClient(main.app) as c:
        yield c


def test_route_create_happy(client):
    r = client.post("/api/ngrok", json={"listener_port": 8443})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["public_url"] == TUN_URL
    assert b["listener_port"] == 8443
    assert b["public_port"] == 18923


def test_route_create_duplicate_409(client):
    assert client.post("/api/ngrok", json={"listener_port": 8443}).status_code == 200
    r = client.post("/api/ngrok", json={"listener_port": 8443})
    assert r.status_code == 409


def test_route_create_inactive_port_400(client):
    r = client.post("/api/ngrok", json={"listener_port": 9999})
    assert r.status_code == 400
    assert "no active listener" in r.json()["detail"]


def test_route_create_without_token_503(client, monkeypatch):
    monkeypatch.delenv("NGROK_AUTHTOKEN", raising=False)
    r = client.post("/api/ngrok", json={"listener_port": 8443})
    assert r.status_code == 503
    assert "NGROK_AUTHTOKEN" in r.json()["detail"]


def test_route_delete_unknown_404(client):
    assert client.delete("/api/ngrok/nope").status_code == 404


def test_route_list_then_delete(client):
    rec = client.post("/api/ngrok", json={"listener_port": 8443}).json()
    assert len(client.get("/api/ngrok").json()) == 1
    assert client.delete(f"/api/ngrok/{rec['id']}").status_code == 200
    assert client.get("/api/ngrok").json() == []


def test_listeners_public_exposure_join(client):
    before = client.get("/api/listeners").json()
    assert before[0]["public_exposure"] is None
    client.post("/api/ngrok", json={"listener_port": 8443})
    after = client.get("/api/listeners").json()
    assert after[0]["public_exposure"]["listener_port"] == 8443
    assert after[0]["public_exposure"]["public_url"] == TUN_URL


def test_close_all_called_on_shutdown(monkeypatch, fake_ngrok):
    from sliver_client import hub
    monkeypatch.setattr(hub, "_connected", True)
    import ngrok_registry
    calls = {"n": 0}
    orig = ngrok_registry.registry.close_all

    async def spy():
        calls["n"] += 1
        await orig()
    monkeypatch.setattr(ngrok_registry.registry, "close_all", spy)

    import main
    with TestClient(main.app):
        pass
    assert calls["n"] >= 1
