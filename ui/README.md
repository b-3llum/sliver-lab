# sliverui

Single-operator browser UI for [Sliver](https://github.com/BishopFox/sliver).

A FastAPI BFF holds a Sliver operator gRPC connection and exposes REST +
WebSocket to a React frontend. Localhost only, no auth.

```
Browser (React + Vite + Tailwind)
   │  WebSocket /events  +  REST /api/*
   ▼
FastAPI BFF (Python 3.11+)
   │  sliver-py (gRPC client)
   ▼
Sliver teamserver
```

## Prerequisites

- Python 3.11+
- Node 18+
- A running Sliver teamserver
- An operator config at `~/.sliver-client/configs/*.cfg` (generated with
  `sliver-server operator …`). To use a different one, set `SLIVER_CFG_PATH`.

## Run (dev)

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .            # or: uv pip install -e .
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```bash
# frontend (separate terminal)
cd frontend
npm install
npm run dev                 # http://127.0.0.1:5173
```

Vite proxies `/api` and `/events` to `127.0.0.1:8000`, so the frontend can
hit the BFF without CORS headaches.

## Pointing at a different Sliver server

The Sliver config file embeds the teamserver address + mTLS material — to
talk to a different server, just point at its `.cfg`:

```bash
SLIVER_CFG_PATH=/path/to/other-operator.cfg uvicorn main:app --reload
```

## Production-ish single binary mode

Build the frontend once, then run the backend alone:

```bash
cd frontend && npm run build
cd ../backend && uvicorn main:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

The backend static-serves `frontend/dist` when present.

## Architecture notes

- **Single upstream event subscription.** `SliverHub` opens *one* gRPC event
  stream and fans events out to all browser WebSockets via per-subscriber
  `asyncio.Queue`s. Don't open N event streams.
- **Reconnect.** If the teamserver drops, the hub retries with exponential
  backoff (1s → 30s). Connection state ships over `bff:state` /
  `bff:connected` / `bff:disconnected` events; the sidebar reflects it.
- **No DB.** Sliver itself is the source of truth. The BFF is stateless
  except for the WS fanout buffer.
- **No auth.** Bind 127.0.0.1, period. If you need remote access, put it
  behind SSH port forwarding or WireGuard — don't add a login page.

## What's wired vs. stubbed

| Surface | Status |
|---|---|
| Sessions, console, beacons, listeners, jobs, files, loot, event drawer | implemented |
| `/api/build` (`Build.tsx`) | **stub — 501** |
| `/api/bofs` (`Bofs.tsx`) | **stub — 501** |
| `/api/profiles` (`Profiles.tsx`) | **stub — 501** |

The stubs return 501 / empty arrays. The frontend views render the response
verbatim so it's obvious what's missing. A separate session will fill them
in (avgen.py integration, BOF catalog, Malleable C2 presets).

## Tests

```bash
cd backend
pip install -e ".[dev]"
pytest
```

Smoke tests stub the Sliver hub so they run without a teamserver — they
verify HTTP wiring and that 501 stubs stay 501.

## Layout

```
sliverui/
├── backend/
│   ├── pyproject.toml
│   ├── main.py             # FastAPI app + static-serve dist
│   ├── config.py           # SLIVER_CFG_PATH / ~/.sliver-client/configs/*
│   ├── sliver_client.py    # SliverHub: singleton client + event fanout
│   ├── ws.py               # /events WebSocket
│   ├── models.py
│   ├── routes/             # sessions, beacons, listeners, jobs, files,
│   │                       # loot + build/bofs/profiles stubs
│   └── tests/
└── frontend/
    ├── package.json, vite, tailwind, ts configs
    └── src/
        ├── api.ts, ws.ts, types.ts
        ├── components/      # Layout, EventDrawer, ui/*
        └── views/           # one per sidebar entry
```
