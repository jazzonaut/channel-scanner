#!/usr/bin/env bash
#
# bootstrap.sh — first-time setup for rtl-sdr-channel-detector.
#
# Safe & idempotent: creates data directories, copies .env.example -> .env if
# missing, probes for an RTL-SDR dongle, and prints next steps. Makes NO
# destructive changes.
set -euo pipefail

# Resolve repo root (this script lives in scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

info()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[32m  ✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m  !\033[0m %s\n' "$*"; }

info "Bootstrapping rtl-sdr-channel-detector in ${REPO_ROOT}"

# --- 1. Docker presence -----------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  ok "docker found: $(docker --version 2>/dev/null || echo 'unknown version')"
else
  warn "docker NOT found. Install Docker Engine / Docker Desktop:"
  warn "    https://docs.docker.com/engine/install/"
fi

# `docker compose` (v2 plugin) vs legacy `docker-compose`.
if docker compose version >/dev/null 2>&1; then
  ok "docker compose (v2) available"
elif command -v docker-compose >/dev/null 2>&1; then
  warn "Only legacy 'docker-compose' found. This project uses 'docker compose' (v2)."
  warn "    Upgrade Docker, or substitute docker-compose in the Makefile."
else
  warn "docker compose NOT found. Install the Compose plugin:"
  warn "    https://docs.docker.com/compose/install/"
fi

# --- 2. Data directories ----------------------------------------------------
info "Creating data directories"
mkdir -p data/db data/recordings data/logs
# Keep the tree tracked even when empty.
[ -f data/.gitkeep ] || : > data/.gitkeep
ok "data/db data/recordings data/logs ready"

# --- 3. .env ----------------------------------------------------------------
if [ -f .env ]; then
  ok ".env already exists (left untouched)"
else
  if [ -f .env.example ]; then
    cp .env.example .env
    ok "Created .env from .env.example (SIMULATION_MODE=true by default)"
  else
    warn ".env.example missing — cannot create .env"
  fi
fi

# --- 4. SDR detection (non-fatal) ------------------------------------------
info "Probing for RTL-SDR hardware (non-fatal)"
if [ -x scripts/detect_sdr.sh ]; then
  bash scripts/detect_sdr.sh || warn "SDR detection reported issues (this is OK for simulation mode)"
else
  warn "scripts/detect_sdr.sh not found or not executable — skipping probe"
fi

# --- 5. USB troubleshooting hints ------------------------------------------
cat <<'EOF'

USB / dongle tips (only relevant when using a real RTL-SDR):
  • Linux kernels claim RTL2832 dongles for DVB-T. Blacklist the DVB drivers:
      echo -e "blacklist dvb_usb_rtl28xxu\nblacklist rtl2832\nblacklist rtl2830" \
        | sudo tee /etc/modprobe.d/blacklist-rtl.conf
      sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
  • Grant non-root USB access with a udev rule (see docs/usb-passthrough.md):
      SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
  • Full guide: docs/usb-passthrough.md and docs/troubleshooting.md

EOF

# --- 6. Done ----------------------------------------------------------------
info "Bootstrap complete."
echo "Next:"
echo "    docker compose up --build      # or: make up"
echo "    open http://localhost:8080"
echo ""
echo "Runs in SIMULATION mode by default — no dongle required."
