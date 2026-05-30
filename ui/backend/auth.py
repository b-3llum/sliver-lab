"""Single shared-token auth for the BFF.

One token guards every /api/* route (except /api/health) and the /events
WebSocket. Set SLIVER_UI_TOKEN to pin the token across restarts; otherwise a
random urlsafe token is generated and logged once to stderr at startup.

The token is accepted as `Authorization: Bearer <token>` for normal requests,
and ALSO as a `?token=<token>` query parameter — browsers can't attach an
Authorization header to a WebSocket handshake, an <img src>, or an <a href>
download, all of which this UI relies on (screenshots, file downloads).
"""
from __future__ import annotations

import logging
import os
import secrets

from fastapi import Header, HTTPException, Query, status

log = logging.getLogger("sliverui.auth")

# Resolved once at startup by load_or_generate_token(). Never persisted.
_TOKEN: str | None = None

UNAUTHORIZED_DETAIL = "unauthorized — paste the UI token"


def load_or_generate_token() -> str:
    """Resolve the auth token. SLIVER_UI_TOKEN wins (used verbatim); otherwise
    generate a random urlsafe token and log it once at WARNING so the operator
    can copy it from the BFF's stderr."""
    global _TOKEN
    env = os.environ.get("SLIVER_UI_TOKEN")
    if env:
        _TOKEN = env
        log.warning("UI auth token loaded from SLIVER_UI_TOKEN")
        return _TOKEN

    _TOKEN = secrets.token_urlsafe(32)
    bar = "=" * 60
    log.warning(
        "\n%s\nUI auth token: %s\n"
        "Use this in the browser modal, or set SLIVER_UI_TOKEN to make\n"
        "it persistent across restarts.\n%s",
        bar, _TOKEN, bar,
    )
    return _TOKEN


def current_token() -> str | None:
    return _TOKEN


def _matches(candidate: str | None) -> bool:
    if not _TOKEN or not candidate:
        return False
    return secrets.compare_digest(candidate, _TOKEN)


def _extract_bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_token(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """HTTP dependency. Accepts the token from the Authorization header
    (preferred) or the `?token=` query param (for header-less img/a GETs)."""
    candidate = _extract_bearer(authorization) or token
    if not _matches(candidate):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UNAUTHORIZED_DETAIL,
        )


def verify_ws_token(token: str | None) -> bool:
    """WebSocket handshake check — the token rides as the `?token=` query
    param since browsers can't set headers on a WS upgrade."""
    return _matches(token)
