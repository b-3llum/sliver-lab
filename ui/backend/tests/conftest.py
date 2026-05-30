"""Shared test setup.

Auth (Phase 7a): a single token now guards every /api route. Rather than thread
a token through each of the ~115 existing requests, an autouse fixture pins the
token to a known value and makes every TestClient send it by default. Tests that
exercise the *unauthenticated* paths (test_auth.py) opt out by mutating
`client.headers` for the specific request.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient as _TestClient

# Known token used across the suite. Real value is irrelevant — it just has to
# match what the BFF resolves at startup (we pin SLIVER_UI_TOKEN to it).
TEST_TOKEN = "test-ui-token-0123456789abcdef"


@pytest.fixture(autouse=True)
def _bff_auth(monkeypatch):
    # Pin the token the lifespan resolves, and the module global directly in
    # case a test pokes the app without going through startup.
    monkeypatch.setenv("SLIVER_UI_TOKEN", TEST_TOKEN)
    import auth
    monkeypatch.setattr(auth, "_TOKEN", TEST_TOKEN, raising=False)

    # Every TestClient created in the suite gets a default Authorization header.
    # Patching the class __init__ (not the imported name) covers all test files
    # regardless of how they imported TestClient.
    orig_init = _TestClient.__init__

    def patched_init(self, *args, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("Authorization", f"Bearer {TEST_TOKEN}")
        orig_init(self, *args, headers=headers, **kwargs)

    monkeypatch.setattr(_TestClient, "__init__", patched_init)
    yield
