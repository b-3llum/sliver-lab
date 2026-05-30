#!/usr/bin/env bash
# One-shot setup for the sliver-lab environment.
#   - checks prerequisites
#   - (optionally) installs Sliver via the official installer
#   - generates an operator config if none exists
#   - creates .env (with a generated UI token) if missing
#   - installs backend (venv) and frontend (pnpm) dependencies
#
# Idempotent: safe to re-run. Does NOT install avgen (not shipped here).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

info(){ printf '\033[1;32m[setup]\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m[setup]\033[0m %s\n' "$*"; }
die(){  printf '\033[1;31m[setup]\033[0m %s\n' "$*" >&2; exit 1; }

# ── prerequisites ─────────────────────────────────────────────────────────
command -v python3 >/dev/null || die "python3 not found (need 3.11+)"
command -v git     >/dev/null || die "git not found"

# Node via nvm if available, else system node
if [ -z "${NVM_DIR:-}" ] && [ -s "$HOME/.nvm/nvm.sh" ]; then export NVM_DIR="$HOME/.nvm"; fi
if [ -s "${NVM_DIR:-/nonexistent}/nvm.sh" ]; then . "$NVM_DIR/nvm.sh"; nvm use 22 >/dev/null 2>&1 || nvm use --lts >/dev/null 2>&1 || true; fi
command -v node >/dev/null || die "node not found (need 18+); install via nvm"
corepack enable >/dev/null 2>&1 || true
command -v pnpm >/dev/null || die "pnpm not found; run 'corepack enable' or 'npm i -g pnpm'"

# ── Sliver ────────────────────────────────────────────────────────────────
if ! command -v sliver-server >/dev/null; then
  warn "sliver-server not found."
  if [ "${SLIVER_INSTALL:-0}" = "1" ]; then
    info "Installing Sliver via the official installer (requires sudo)…"
    curl -fsSL https://sliver.sh/install | sudo bash
  else
    warn "Install it yourself, then re-run, e.g.:"
    warn "    curl -fsSL https://sliver.sh/install | sudo bash"
    warn "(or re-run with SLIVER_INSTALL=1 to do it now)"
  fi
fi

# ── operator config ───────────────────────────────────────────────────────
CFG_DIR="$HOME/.sliver-client/configs"
mkdir -p "$CFG_DIR"
if ! ls "$CFG_DIR"/*.cfg >/dev/null 2>&1; then
  if command -v sliver-server >/dev/null; then
    info "Generating an operator config (localhost)…"
    sliver-server operator --name "${USER:-operator}" --lhost 127.0.0.1 --save "$CFG_DIR" || \
      warn "Could not generate operator config automatically; create one with 'sliver-server operator …'"
  else
    warn "Skipping operator config generation (sliver-server missing)."
  fi
fi

# ── .env ──────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  TOKEN="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)"
  sed -i "s/^SLIVER_UI_TOKEN=.*/SLIVER_UI_TOKEN=${TOKEN}/" .env
  info ".env created with a generated SLIVER_UI_TOKEN."
else
  info ".env already present — leaving it untouched."
fi

# ── backend ───────────────────────────────────────────────────────────────
info "Installing backend (venv + deps)…"
( cd ui/backend
  [ -d .venv ] || python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -e . )

# ── frontend ──────────────────────────────────────────────────────────────
info "Installing frontend deps (pnpm)…"
( cd ui/frontend
  pnpm install --config.dangerouslyAllowAllBuilds=true )

info "Done. Start everything with:  scripts/start.sh   (or 'make up')"
info "Then open http://127.0.0.1:5173 and paste SLIVER_UI_TOKEN from your .env."
