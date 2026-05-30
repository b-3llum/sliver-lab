"""Console live-audit fixes — backend pieces of bugs 1 & 3.

  * Bug 3: binary task results (screenshot/download) must survive byte-for-byte
    — no _pb_to_dict UTF-8 decode/re-encode round-trip. Plus the screenshot/
    download response `kind` must reflect the implant, not hardcode "beacon".
  * Bug 1: the download task result carries the path basename as `filename`
    so the console can label the download link.

The pure-function extract tests use REAL sliver_pb2 protos (real _pb_to_dict),
which is what exposes the mangling.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── Pure-function: binary bytes survive extraction ─────────────────

def test_screenshot_extract_preserves_png_bytes():
    from routes.implants import _screenshot_bytes
    from sliver.pb.sliverpb import sliver_pb2 as s
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256))  # magic byte + every byte value
    out = _screenshot_bytes(s.Screenshot(Data=png))
    assert out == png
    assert out[0] == 0x89  # not 0xEF (U+FFFD replacement)


def test_download_extract_preserves_binary_bytes():
    from routes.implants import _download_bytes
    from sliver.pb.sliverpb import sliver_pb2 as s
    blob = bytes(range(256)) * 4
    out = _download_bytes(s.Download(Path="x", Data=blob))  # no Encoder → raw
    assert out == blob


def test_download_extract_gunzips_when_encoder_is_gzip():
    """Sliver gzip-encodes downloads (Encoder='gzip'); the extract must decode
    so the operator gets the real file content, not a gzip stream."""
    import gzip as _gz
    from routes.implants import _download_bytes
    from sliver.pb.sliverpb import sliver_pb2 as s
    plain = b"5dfg5hd1hgl5ysl5gn1fxj5azdbcvxvgj5632asfrg"
    dl = s.Download(Path="x", Data=_gz.compress(plain), Encoder="gzip")
    assert _download_bytes(dl) == plain


# ── Route fixtures (mocked sliver-py) ──────────────────────────────

class _FakeImplant:
    def __init__(self, ID: str):
        self.ID = ID
        self.Name = "X"; self.Hostname = "winbox"; self.Username = "user"
        self.OS = "windows"; self.Arch = "amd64"; self.Transport = "mtls"
        self.RemoteAddress = "10.1.0.7:1000"; self.Pid = 100
        self.UID = "0"; self.GID = "0"; self.LastCheckin = 0; self.IsDead = False
        self.Filename = ""; self.ActiveC2 = ""; self.NextCheckin = 0
        self.Interval = 60; self.Jitter = 10
        self.TasksCount = 0; self.TasksCountCompleted = 0


@pytest.fixture
def fake_client():
    c = MagicMock()
    c.sessions = AsyncMock(return_value=[])
    c.beacons = AsyncMock(return_value=[])
    c.jobs = AsyncMock(return_value=[])
    c.beacon_tasks = AsyncMock(return_value=[])
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
    monkeypatch.setattr("sliver_client._pb_to_dict", fake_pb)
    monkeypatch.setattr("routes.implants._pb_to_dict", fake_pb)

    import main
    with TestClient(main.app) as c:
        yield c


def _poll(client, tid, n=60):
    st = None
    for _ in range(n):
        st = client.get(f"/api/tasks/{tid}").json()
        if st["state"] in ("complete", "error"):
            break
    return st


# ── Bug 3: screenshot kind label + byte-perfect /result ────────────

def test_screenshot_on_session_returns_session_kind_and_clean_bytes(client, fake_client):
    from sliver.pb.sliverpb import sliver_pb2 as s
    sid = "aaaaaaaa-1111-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    png = b"\x89PNG\r\n\x1a\nDESKTOP\xff\xfe\x00"
    interactive = MagicMock()
    interactive.screenshot = AsyncMock(return_value=s.Screenshot(Data=png))
    fake_client.interact_session = AsyncMock(return_value=interactive)

    r = client.post(f"/api/implants/{sid}/screenshot")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "session"          # ← bug-3 label fix (was "beacon")
    assert "task_id" in body

    st = _poll(client, body["task_id"])
    assert st["state"] == "complete", st

    res = client.get(f"/api/tasks/{body['task_id']}/result")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content == png                  # ← byte-for-byte, no UTF-8 mangle


def test_screenshot_on_beacon_returns_beacon_kind(client, fake_client):
    bid = "bbbbbbbb-2222-2222-2222-222222222222"
    fake_client.beacons.return_value = [_FakeImplant(bid)]
    interactive = MagicMock()
    interactive.beacon_tasks = {}
    interactive.timeout = 30
    interactive._request = lambda pb: pb

    async def fake_screenshot():
        import asyncio
        return asyncio.Future()  # never resolves; we only assert the POST shape
    interactive.screenshot = fake_screenshot
    fake_client.interact_beacon = AsyncMock(return_value=interactive)

    r = client.post(f"/api/implants/{bid}/screenshot")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "beacon"            # ← per-implant label, not per-task-type
    assert "task_id" in body


# ── Bug 1: download result carries the basename as `filename` ──────

def test_download_on_session_result_has_basename_and_clean_bytes(client, fake_client):
    from sliver.pb.sliverpb import sliver_pb2 as s
    sid = "cccccccc-3333-1111-1111-111111111111"
    fake_client.sessions.return_value = [_FakeImplant(sid)]
    content = b"5dfg5hd1hgl5ysl5gn1fxj5azdbcvxvgj5632asfrg"
    interactive = MagicMock()
    interactive.download = AsyncMock(return_value=s.Download(Path="x", Data=content))
    fake_client.interact_session = AsyncMock(return_value=interactive)

    r = client.post(f"/api/implants/{sid}/download",
                    json={"path": "C:\\Users\\user\\Desktop\\flag.txt"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "session"

    st = _poll(client, body["task_id"])
    assert st["state"] == "complete", st
    assert st["result"]["filename"] == "flag.txt"   # ← bug-1 link text

    res = client.get(f"/api/tasks/{body['task_id']}/result")
    assert res.status_code == 200
    assert res.content == content
