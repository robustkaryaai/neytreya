#!/usr/bin/env bash
# ──────────────────────────────────────────────
#  Neytreya — Perceptual Intelligence
#  Launch script: Starts Electron UI directly
# ──────────────────────────────────────────────
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ELECTRON_DIR="$DIR/electron"

# ── 1. Electron deps check ────────────────────
if [ ! -d "$ELECTRON_DIR/node_modules" ]; then
  echo "▸ Installing Electron dependencies…"
  cd "$ELECTRON_DIR" && npm install && cd "$DIR"
fi

# ── 2. Start Electron UI ──────────────────────
echo "▸ Starting Neytreya UI…"
cd "$ELECTRON_DIR"
npx electron .
