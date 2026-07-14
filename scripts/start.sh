#!/usr/bin/env bash
#
# start.sh — start the app in the background and print the URL.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

COMPOSE="docker compose"
if ! docker compose version >/dev/null 2>&1; then
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  else
    echo "ERROR: docker compose not available. See scripts/bootstrap.sh output." >&2
    exit 1
  fi
fi

# Ensure .env exists so env_file doesn't fail.
if [ ! -f .env ] && [ -f .env.example ]; then
  echo "No .env found — creating one from .env.example"
  cp .env.example .env
fi

# Determine the port (default 8080), honoring WEB_PORT from .env if set.
WEB_PORT="$(grep -E '^WEB_PORT=' .env 2>/dev/null | tail -n1 | cut -d= -f2 || true)"
WEB_PORT="${WEB_PORT:-8080}"

echo "Starting rtl-sdr-channel-detector..."
${COMPOSE} up -d --build

echo ""
echo "Started. Web UI: http://localhost:${WEB_PORT}"
echo "Follow logs:     ${COMPOSE} logs -f    (or: make logs)"
echo "Stop:            ${COMPOSE} down       (or: make down)"
