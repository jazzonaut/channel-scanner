#!/usr/bin/env bash
#
# detect_sdr.sh — probe the host for an RTL-SDR dongle and report findings.
#
# Non-fatal: always exits 0 unless something unexpected happens. Gracefully
# handles missing tools (lsusb / rtl_test / SoapySDRUtil may not be installed).
set -euo pipefail

info()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[32m  ✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m  !\033[0m %s\n' "$*"; }

FOUND=0

info "Detecting RTL-SDR hardware..."

# --- lsusb ------------------------------------------------------------------
if command -v lsusb >/dev/null 2>&1; then
  # Realtek RTL2832U dongles enumerate as vendor 0bda, product 2838 (or 2832).
  if lsusb | grep -Eiq 'Realtek|RTL2838|RTL2832|0bda:2838|0bda:2832'; then
    ok "RTL-SDR-like USB device found:"
    lsusb | grep -Ei 'Realtek|RTL283[0-9]|0bda:28' | sed 's/^/      /' || true
    FOUND=1
  else
    warn "No Realtek/RTL2832 device seen in lsusb output."
  fi
else
  warn "lsusb not found (install 'usbutils') — skipping USB enumeration."
fi

# --- rtl_test ---------------------------------------------------------------
if command -v rtl_test >/dev/null 2>&1; then
  info "Running 'rtl_test' (2s)..."
  # rtl_test blocks; cap it. It prints device info to stderr.
  if timeout 2s rtl_test -t 2>&1 | sed 's/^/      /'; then
    :
  fi
  # Detect the classic "usb_claim_interface error -6" (kernel driver conflict).
  if timeout 2s rtl_test 2>&1 | grep -qi 'usb_claim_interface error'; then
    warn "rtl_test could not claim the device (kernel DVB driver conflict?)."
    warn "See the DVB-driver guidance below."
  fi
else
  warn "rtl_test not found (install 'rtl-sdr') — skipping device self-test."
fi

# --- SoapySDR ---------------------------------------------------------------
if command -v SoapySDRUtil >/dev/null 2>&1; then
  info "Running 'SoapySDRUtil --find'..."
  SoapySDRUtil --find 2>&1 | sed 's/^/      /' || true
else
  warn "SoapySDRUtil not found — skipping SoapySDR probe (optional)."
fi

# --- Kernel driver / udev guidance -----------------------------------------
cat <<'EOF'

If a dongle is plugged in but not usable:

  1) The Linux kernel's DVB-T driver often claims RTL2832 dongles. Blacklist it:
       printf 'blacklist dvb_usb_rtl28xxu\nblacklist rtl2832\nblacklist rtl2830\n' \
         | sudo tee /etc/modprobe.d/blacklist-rtl.conf
       sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
     Then re-plug the dongle.

  2) Permission denied? Add a udev rule so non-root users can access it:
       # /etc/udev/rules.d/99-rtl-sdr.rules
       SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
       sudo udevadm control --reload-rules && sudo udevadm trigger

  Full guide: docs/usb-passthrough.md and docs/troubleshooting.md
EOF

if [ "${FOUND}" -eq 1 ]; then
  ok "Detection finished: a candidate RTL-SDR device was seen."
else
  warn "Detection finished: no RTL-SDR device confirmed."
  warn "That's fine — the app runs in SIMULATION_MODE without hardware."
fi

# Always succeed (non-fatal probe).
exit 0
