"""FastAPI entry point.

- Boots SliverHub on startup, tears it down on shutdown.
- Mounts /api/* routers.
- Mounts /events WebSocket.
- Serves the built frontend from frontend/dist if present.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from auth import load_or_generate_token, require_token
from routes import (
    audit, beacons, bofs, build, build_sliver, files, graph, implants, jobs,
    listeners, loot, ngrok, operators, profiles, report, sessions, tasks, tunnels,
)
from task_registry import registry as task_registry
from tunnel_registry import reap_orphans, tunnel_registry
from ngrok_registry import registry as ngrok_registry
from sliver_client import hub
from ws import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sliverui")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("Starting SliverHub")
    # Resolve the UI auth token before accepting requests (logs it once).
    load_or_generate_token()
    # Route task_update events through the same WS the browser already
    # listens on. hub._broadcast is "private" by underscore convention but
    # owned by us; no public alias exists yet.
    task_registry.set_broadcaster(hub._broadcast)
    # Sweep up any leftover sliver-client subprocesses from a prior BFF
    # crash/restart so their listener sockets free up before we let any
    # tunnel route try to bind the same port again.
    reaped = reap_orphans()
    if reaped:
        log.info("tunnel orphan reaper: SIGTERM sent to %d sliver-client process(es)", reaped)
    # ngrok orphan reaper: SDK tunnels are in-process and die with the previous
    # BFF, so there's nothing to reap across restarts — but tear down any agent
    # session this process might somehow hold, mirroring the Phase 5 pattern.
    try:
        import ngrok as _ngrok
        _ngrok.kill()
    except Exception:  # noqa: BLE001 — no session/agent yet; harmless
        pass
    await hub.start()
    try:
        yield
    finally:
        log.info("Stopping SliverHub")
        await ngrok_registry.close_all()
        await tunnel_registry.close_all()
        await hub.stop()


app = FastAPI(title="Sliver Operator UI", version="0.1.0", lifespan=lifespan)

# Vite dev server runs on a different port; backend is 127.0.0.1 only so this
# is safe enough for solo-operator localhost use.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# /api/health is intentionally unauthenticated so monitoring can probe
# liveness without the token. Everything else requires it (CORS preflight
# OPTIONS is short-circuited by the middleware before the dependency runs).
@app.get("/api/health")
async def health():
    return {"ok": True, **hub.state().model_dump()}


for r in (sessions.router, beacons.router, listeners.router, jobs.router,
          files.router, build.router, build_sliver.router, bofs.router,
          profiles.router, loot.router, graph.router, implants.router,
          tasks.router, tunnels.router, audit.router, operators.router,
          ngrok.router, report.router):
    app.include_router(r, dependencies=[Depends(require_token)])

# WS auth is handled inside the handler (query-param token → close 1008),
# not via the HTTP dependency, since browsers can't header-auth a WS upgrade.
app.include_router(ws_router)

# Static-serve built frontend if it exists. During dev, use Vite at :5173.
DIST = Path(__file__).parent.parent / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="frontend")
