#!/usr/bin/env bash
#
# stop.sh — stop the app.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

COMPOSE="docker compose"
if ! docker compose version >/dev/null 2>&1; then
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  else
    echo "ERROR: docker compose not available." >&2
    exit 1
  fi
fi

echo "Stopping rtl-sdr-channel-detector..."
${COMPOSE} down
echo "Stopped."
