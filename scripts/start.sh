#!/usr/bin/env bash
# Start the full stack in order: teamserver -> backend (BFF) -> frontend.
# Teamserver runs under a memory-capped systemd user scope. Logs go to /tmp.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
[ -f .env ] || { echo "no .env — run scripts/setup.sh first"; exit 1; }
set -a; . ./.env; set +a

info(){ printf '\033[1;32m[start]\033[0m %s\n' "$*"; }

# 1) Teamserver
if ! pgrep -f "sliver-server daemon" >/dev/null; then
  info "starting sliver-server daemon (mem-capped scope)…"
  systemd-run --user --scope -p MemoryMax=2G -p MemorySwapMax=0 \
    bash -c 'exec sliver-server daemon > /tmp/sliver-server.log 2>&1' &
  for i in $(seq 1 30); do ss -tlnp 2>/dev/null | grep -q ':31337' && break; sleep 1; done
else
  info "sliver-server already running."
fi

# 2) Backend (BFF)
if ! ss -tlnp 2>/dev/null | grep -q "127.0.0.1:${PORT:-8000}"; then
  info "starting backend on 127.0.0.1:${PORT:-8000}…"
  ( cd ui/backend
    nohup ./.venv/bin/uvicorn main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" \
      > /tmp/bff.log 2>&1 & )
  for i in $(seq 1 20); do curl -sf "http://${HOST:-127.0.0.1}:${PORT:-8000}/api/health" >/dev/null 2>&1 && break; sleep 1; done
else
  info "backend already running."
fi

# 3) Frontend (Vite)
if ! ss -tlnp 2>/dev/null | grep -q ':5173'; then
  info "starting frontend on 127.0.0.1:5173…"
  if [ -z "${NVM_DIR:-}" ] && [ -s "$HOME/.nvm/nvm.sh" ]; then export NVM_DIR="$HOME/.nvm"; fi
  if [ -s "${NVM_DIR:-/nonexistent}/nvm.sh" ]; then . "$NVM_DIR/nvm.sh"; nvm use 22 >/dev/null 2>&1 || true; fi
  ( cd ui/frontend
    nohup ./node_modules/.bin/vite --host 127.0.0.1 --port 5173 --strictPort \
      > /tmp/vite.log 2>&1 & )
else
  info "frontend already running."
fi

info "open http://127.0.0.1:5173  (token = SLIVER_UI_TOKEN in .env)"
