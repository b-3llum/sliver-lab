#!/usr/bin/env bash
# Stop the stack. By default leaves the teamserver running (it holds C2 state);
# pass --all to stop the teamserver too.
set -uo pipefail
info(){ printf '\033[1;33m[stop]\033[0m %s\n' "$*"; }

info "stopping frontend (vite)…"; pkill -f "vite --host 127.0.0.1 --port 5173" 2>/dev/null || true
info "stopping backend (uvicorn)…"; pkill -f "uvicorn main:app" 2>/dev/null || true

if [ "${1:-}" = "--all" ]; then
  info "stopping sliver-server daemon…"; pkill -f "sliver-server daemon" 2>/dev/null || true
else
  info "leaving sliver-server running (use --all to stop it)."
fi
info "done."
