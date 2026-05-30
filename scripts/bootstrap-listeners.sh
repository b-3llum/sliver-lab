#!/usr/bin/env bash
# Bring up a couple of mTLS C2 listeners on the teamserver (idempotent-ish).
# Requires sliver-client + a teamserver running. Edit the ports as you like.
set -euo pipefail
PORTS=("${@:-8443 9001}")

command -v sliver-client >/dev/null || { echo "sliver-client not found"; exit 1; }

for p in ${PORTS[@]}; do
  echo "[listeners] starting mtls listener on :$p"
  sliver-client -i <<EOF || true
mtls --lport $p
exit
EOF
done
echo "[listeners] done. Check the Listeners / Jobs tab in the UI."
