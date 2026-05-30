# sliver-lab

Quick-install, reproducible **red-team lab** built around the
[Sliver](https://github.com/BishopFox/sliver) C2 framework and a single-operator
browser **Operator UI**. One `setup.sh` brings up the teamserver, the UI backend
(FastAPI BFF), and the React frontend, with optional ngrok exposure.

> ⚠️ **Authorized use only.** Sliver is an adversary-emulation / C2 framework. Use this
> lab **only** against systems you own or are explicitly authorized to test. Keep
> everything bound to `127.0.0.1`. See [SECURITY](#security).

> **avgen is not included.** The Build tab has an *optional* hook (`AVGEN_PATH`) for a
> user-supplied `avgen.py` payload builder. This repo intentionally ships **without** it
> and with the path empty, so the avgen panel stays disabled (`avgen_present=false`) until
> you point it at your own copy. Sliver-native implant builds work without it.

---

## What's in here

```
sliver-lab/
├── README.md
├── .env.example          # copy to .env (setup.sh generates the UI token)
├── Makefile              # make setup | up | down | status | logs | compose-up
├── docker-compose.yml    # run the UI in containers (teamserver on host)
├── scripts/
│   ├── setup.sh          # one-shot installer / bootstrapper
│   ├── start.sh          # teamserver → backend → frontend (in order)
│   ├── stop.sh           # stop UI (use --all to stop teamserver too)
│   ├── status.sh         # ports / processes / BFF health
│   └── bootstrap-listeners.sh   # start default mTLS listeners
├── systemd/
│   └── sliver-teamserver.service  # optional mem-capped user unit
├── ui/                   # the Operator UI (backend + frontend)
└── docs/
    ├── Sliver-Operator-UI-Manual.md   # full illustrated wiki
    └── images/sliver-operator-manual/ # screenshots
```

## Prerequisites

- Python 3.11+, Node 18+ (Node 22 recommended, via `nvm`), `pnpm` (via `corepack`)
- `sliver-server` / `sliver-client` (setup.sh can install via the official installer)
- Linux with `systemd` (for the memory-capped teamserver scope) — optional

## Quick start

```bash
git clone <your-private-repo-url> sliver-lab && cd sliver-lab

# install deps, generate .env (+ a random UI token) and an operator config
./scripts/setup.sh          # or: make setup
#   re-run with SLIVER_INSTALL=1 to also install Sliver via the official installer

# start teamserver + backend + frontend
./scripts/start.sh          # or: make up

# (optional) start a couple of mTLS listeners
./scripts/bootstrap-listeners.sh 8443 9001   # or: make listeners
```

Open **http://127.0.0.1:5173** and paste the `SLIVER_UI_TOKEN` from your `.env`
(it's also logged to the BFF stderr / `/tmp/bff.log` on startup).

Check health any time:

```bash
./scripts/status.sh         # or: make status
```

## Run the UI in Docker instead

```bash
make compose-up             # teamserver must already be running on the host
```

## The UI

See **[docs/Sliver-Operator-UI-Manual.md](docs/Sliver-Operator-UI-Manual.md)** — a full,
illustrated wiki of every screen (Sessions, Console, Tunnels, Beacons, Graph, Listeners,
Jobs, Files, Loot, Build, BOFs, Profiles, Audit), the architecture, and the end-to-end
lab workflow.

## Enabling avgen yourself (optional)

The Build tab's avgen panel stays disabled until you supply your own builder:

```bash
# in .env
AVGEN_PATH=/absolute/path/to/your/avgen.py
```

Restart the backend; the Build tab will introspect its arguments automatically. This repo
neither ships nor installs avgen.

## SECURITY

- **Localhost only.** The UI's only auth is one shared token. Keep the BFF and frontend on
  `127.0.0.1`; for remote access use SSH port-forwarding or WireGuard — don't add a public
  login page.
- **Secrets stay out of git.** `.env` and `*.cfg` (operator configs / mTLS material) are
  git-ignored. Never commit them.
- **ngrok is high-risk.** Setting `NGROK_AUTHTOKEN` lets the Listeners tab expose a C2
  listener to the public internet. The mTLS chain still gates implants, but anyone who
  reaches the address can attempt a handshake — only expose authorized infrastructure, and
  close the tunnel when done.
- **Stay in scope.** Build, deliver, and run implants only against systems you own or are
  authorized to test.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `npm/node not found` | `export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22` |
| pnpm "approve-builds" / install fails | `pnpm install --config.dangerouslyAllowAllBuilds=true` then launch Vite directly |
| First page load slow/times out | Vite re-optimizes deps on first load; wait for `ready in …` in `/tmp/vite.log` |
| UI keeps asking for token | token must match `SLIVER_UI_TOKEN`; ensure backend started with `.env` loaded |
| Sidebar shows disconnected | teamserver down / `SLIVER_CFG_PATH` invalid — check `/tmp/sliver-server.log`, port `:31337` |
| ngrok controls return 503 | `NGROK_AUTHTOKEN` not set in `.env` |

Logs: `make logs` (tails `/tmp/sliver-server.log`, `/tmp/bff.log`, `/tmp/vite.log`).
