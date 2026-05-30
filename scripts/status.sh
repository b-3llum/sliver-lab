#!/usr/bin/env bash
# Health snapshot of the stack.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="$( ( [ -f "$REPO/.env" ] && . "$REPO/.env"; echo "${PORT:-8000}") )"

echo "── ports ──"
ss -tlnp 2>/dev/null | grep -E ':31337|:8443|:9001|:5173|:'"$PORT" || echo "  (none of the expected ports are listening)"

echo "── processes ──"
pgrep -af "sliver-server daemon" | sed 's/^/  /' || echo "  teamserver: down"
pgrep -af "uvicorn main:app"     | sed 's/^/  /' || echo "  backend: down"
pgrep -af "vite --host 127.0.0.1 --port 5173" | sed 's/^/  /' || echo "  frontend: down"

echo "── BFF health ──"
curl -s "http://127.0.0.1:${PORT}/api/health" 2>/dev/null | python3 -m json.tool 2>/dev/null \
  || echo "  backend not responding on :$PORT"
