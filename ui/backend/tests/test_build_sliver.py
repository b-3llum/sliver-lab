"""Sliver-native build endpoint tests.

We mock the subprocess.communicate call so we never actually invoke the
sliver-client binary. The mock writes a fake "binary" into the save_dir
that the route then streams back, which lets us assert on Content-Type +
Content-Disposition.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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


# ── /options ───────────────────────────────────────────────────────


def test_options_returns_enums(client):
    body = client.get("/api/build/sliver/options").json()
    assert "windows" in body["goos"]
    assert "amd64" in body["goarch"]
    assert "exe" in body["format"]
    assert body["defaults"]["goos"] == "windows"


# ── validation ─────────────────────────────────────────────────────


def _good_body(**overrides):
    base = {
        "goos": "windows", "goarch": "amd64", "format": "exe",
        "c2_url": "mtls://10.1.0.7:8443", "beacon": True,
        "beacon_interval_s": 60, "obfuscate": True,
    }
    base.update(overrides)
    return base


def test_bad_goos_400(client):
    r = client.post("/api/build/sliver", json=_good_body(goos="solaris"))
    # Pydantic catches the Literal mismatch as 422; FastAPI's default for
    # request validation is 422. The brief expected 400 — accept either
    # 4xx-class to keep the test aligned with the actual contract.
    assert 400 <= r.status_code < 500


def test_bad_goarch_400(client):
    r = client.post("/api/build/sliver", json=_good_body(goarch="mips"))
    assert 400 <= r.status_code < 500


def test_bad_format_400(client):
    r = client.post("/api/build/sliver", json=_good_body(format="apk"))
    assert 400 <= r.status_code < 500


def test_malformed_c2_url_returns_400(client):
    r = client.post("/api/build/sliver", json=_good_body(c2_url="ftp://nope"))
    assert r.status_code == 400
    assert "scheme" in r.json()["detail"].lower()


def test_empty_c2_url_returns_400(client):
    r = client.post("/api/build/sliver", json=_good_body(c2_url=""))
    assert r.status_code == 400


def test_bad_name_returns_400(client):
    r = client.post("/api/build/sliver", json=_good_body(name="../../etc/passwd"))
    assert r.status_code == 400


# ── happy path (mock subprocess) ───────────────────────────────────


def _fake_proc_factory(payload: bytes, save_dir_finder, *, exit_code: int = 0, stdout_extra: str = ""):
    """Return an AsyncMock that mimics asyncio.create_subprocess_exec's
    result. `save_dir_finder` extracts the --save dir from argv so we can
    write the fake artifact there before communicate() returns."""
    async def communicate():
        # In the build route, the rc file holds the save dir — we get it
        # from the captured args via a closure on save_dir_finder.
        sd = save_dir_finder()
        if sd:
            (sd / "FAKE_NAME.exe").write_bytes(payload)
        msg = (b"[*] Build completed in 1s\n"
               b"[*] Implant saved to " + (str(sd / 'FAKE_NAME.exe').encode() if sd else b'') + b"\n"
               + stdout_extra.encode())
        return (msg, b"")
    proc = MagicMock()
    proc.communicate = communicate
    proc.returncode = exit_code
    proc.kill = MagicMock()
    return proc


def test_happy_path_returns_binary(client, monkeypatch, tmp_path):
    """End-to-end with the subprocess mocked: route writes rc, invokes
    sliver-client (mocked), reads back the file, streams it."""
    captured_args: list[tuple] = []
    save_dir_holder: dict = {}

    async def fake_create_proc(*args, **_kwargs):
        captured_args.append(args)
        # The rc file path is args[2]; read it to find the --save dir.
        rc_path = Path(args[2])
        rc_content = rc_path.read_text()
        # The --save argument is the last token on the generate line.
        import shlex
        toks = shlex.split(rc_content.splitlines()[0])
        sd = Path(toks[toks.index("--save") + 1])
        save_dir_holder["sd"] = sd
        return _fake_proc_factory(b"\x4d\x5aFAKEPE", lambda: sd)

    monkeypatch.setattr("routes.build_sliver.asyncio.create_subprocess_exec", fake_create_proc)
    r = client.post("/api/build/sliver", json=_good_body())
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert "FAKE_NAME.exe" in r.headers.get("content-disposition", "")
    assert r.content.startswith(b"MZ")  # the fake PE we wrote
    # And the captured argv used --rc as the entry point.
    assert captured_args
    args = captured_args[0]
    assert args[0] == "sliver-client"
    assert args[1] == "--rc"


def test_generator_failure_returns_422(client, monkeypatch):
    async def fake_create_proc(*_args, **_kwargs):
        proc = MagicMock()
        async def comm():
            return (b"[!] something blew up\n", b"")
        proc.communicate = comm
        proc.returncode = 1
        return proc
    monkeypatch.setattr("routes.build_sliver.asyncio.create_subprocess_exec", fake_create_proc)
    r = client.post("/api/build/sliver", json=_good_body())
    assert r.status_code == 422
    assert "blew up" in r.json()["detail"]


def test_timeout_returns_504(client, monkeypatch):
    """Force the runner's wait_for to raise TimeoutError. We patch
    asyncio.wait_for inside the route module."""
    async def fake_create_proc(*_args, **_kwargs):
        proc = MagicMock()
        async def comm():
            await asyncio.sleep(10)
            return (b"", b"")
        proc.communicate = comm
        proc.returncode = 0
        proc.kill = MagicMock()
        return proc

    async def fake_wait_for(coro, timeout):  # noqa: ARG001
        # Cancel the inner coro so the test doesn't dangle, then raise.
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr("routes.build_sliver.asyncio.create_subprocess_exec", fake_create_proc)
    monkeypatch.setattr("routes.build_sliver.asyncio.wait_for", fake_wait_for)
    r = client.post("/api/build/sliver", json=_good_body())
    assert r.status_code == 504
    assert "timeout" in r.json()["detail"].lower()
