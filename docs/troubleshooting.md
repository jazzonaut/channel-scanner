# Troubleshooting

Most issues fall into hardware/USB, tuning/DSP, web, database, or ESP32. Work
top-down. Remember: with `SIMULATION_MODE=true` (default) the app runs fully
without any dongle, which is a quick way to isolate hardware problems.

---

## No RTL-SDR found

Symptoms: `/api/device` reports `available:false`; logs say no device.

- Confirm the OS sees it: `lsusb | grep -Ei 'Realtek|RTL2838|0bda:2838'`.
- Run the probe: `bash scripts/detect_sdr.sh`.
- Check the cable/port (use a direct USB port, avoid unpowered hubs).
- If it appears on the host but not in the container, see
  "USB visible on host but not in Docker" below.
- If nothing appears at all, the DVB driver or a bad cable is the usual cause.

## Permission denied (opening the device)

Symptoms: `usb_open error -3`, `Permission denied`, or the backend falls back to
simulation.

- Add the udev rule and reload (see [usb-passthrough.md](usb-passthrough.md) §3):
  ```bash
  SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
  sudo udevadm control --reload-rules && sudo udevadm trigger
  ```
- Ensure the container has the cgroup rule `c 189:* rmw` and the
  `/dev/bus/usb` device mapping (both are in `docker-compose.yml`).
- Re-plug the dongle after changing udev rules.

## Kernel DVB driver claiming the dongle

Symptoms: `usb_claim_interface error -6`; `rtl_test` says the device is in use.

- The kernel's DVB-T driver grabbed it. Blacklist and unload:
  ```bash
  printf 'blacklist dvb_usb_rtl28xxu\nblacklist rtl2832\nblacklist rtl2830\n' \
    | sudo tee /etc/modprobe.d/blacklist-rtl.conf
  sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
  ```
- Re-plug the dongle; verify with `rtl_test -t`.

## USB visible on host but not in Docker

Symptoms: `lsusb` on the host shows the dongle; inside the container it's absent.

- Confirm compose has both:
  ```yaml
  devices:            [ "/dev/bus/usb:/dev/bus/usb" ]
  device_cgroup_rules: [ "c 189:* rmw" ]
  ```
- Recreate the container after editing compose: `docker compose up -d --force-recreate`.
- Check inside: `docker compose exec app lsusb`.
- **Docker Desktop (macOS/Windows) does not pass USB through** — use
  `SIMULATION_MODE=true` or a native Linux host. See usb-passthrough.md.
- As an explicit last resort only, the commented `privileged: true` block.

## Failed tuning

Symptoms: errors setting center frequency; `/api/device` `freq_range_hz` excludes
your target.

- Keep `SCAN_START_HZ`/`SCAN_END_HZ` inside the tuner's range (R820T ≈ 24 MHz–1.7 GHz).
- Set `SDR_PPM` to your dongle's measured error if edges look shifted.
- Very low gain can make weak targets invisible; try `SDR_GAIN=auto` first.

## Unsupported sample rate

Symptoms: `Failed to set sample rate` / dropped samples.

- RTL-SDR reliably supports up to ~2.56 MS/s; 2.4 MS/s (`SDR_SAMPLE_RATE=2400000`)
  is a safe default. Rates in the ~300 kS/s–900 kS/s gap are unstable — avoid.
- Lower the rate if you see USB transfer errors on marginal hardware/hubs.

## FFT overload / high CPU / dropped frames

Symptoms: `/api/metrics` shows rising `dropped_frames` or `queue_depth`;
spectrum stutters.

- Reduce `FFT_SIZE` (e.g. 1024), lower `SPECTRUM_FPS` and/or `SPECTRUM_BINS`.
- Increase `SCAN_DWELL_MS` slightly to reduce retune churn.
- Give the container more CPU, or narrow the scan span.

## Browser WebSocket disconnects

Symptoms: spectrum freezes; UI shows "reconnecting"; `/ws/live` drops.

- Check the app is healthy: `curl -f http://localhost:8080/api/health`.
- A reverse proxy in front must allow WebSocket upgrades (`Upgrade`/`Connection`
  headers) and not buffer `/ws/live`.
- Idle proxies may time out; the client auto-reconnects — confirm the server
  ping/pong keepalive isn't blocked.
- Look at `docker compose logs -f` for server-side errors around the drop.

## Database locked

Symptoms: `sqlite3.OperationalError: database is locked`.

- SQLite allows one writer at a time. Avoid opening the DB file with external
  tools while the app runs.
- Don't place the DB on a network/overlay filesystem that breaks locking; the
  default `/data/db` bind mount to a local disk is fine.
- If corrupted, stop the app and reset with `bash scripts/reset_data.sh`
  (this deletes data — see the prompt).

## ESP32 upload failure

Symptoms: `pio run --target upload` fails; "could not open port", timeout, or
"failed to connect: No serial data received".

- Confirm the port and that no serial monitor holds it (`make esp32-monitor`
  must be closed first).
- Serial ports per OS:
  - **Linux:** `/dev/ttyUSB0` or `/dev/ttyACM0` — add yourself to `dialout`:
    `sudo usermod -aG dialout $USER` (log out/in).
  - **macOS:** `/dev/cu.SLAB_USBtoUART` or `/dev/cu.usbserial-*` (install the
    CP210x/CH340 driver).
  - **Windows:** `COM3`, `COM4`, … (check Device Manager).
- Some boards need the **BOOT** button held during upload to enter flash mode.
- Try a lower upload speed and a known-good **data** USB cable (not charge-only).

## ESP32 Wi-Fi failure

Symptoms: board never connects; can't reach the app; watchdog resets.

- Set correct SSID/password in the firmware's `secrets.h` (gitignored).
- ESP32 Wi-Fi is **2.4 GHz only** — it will not join a 5 GHz-only SSID.
- Ensure the app's host is reachable from the board's network and the base URL
  (host:8080) is correct; captive-portal networks will block it.
- Watch the serial monitor (`make esp32-monitor`) for the connection state and
  IP address.

---

If none of this helps, capture `docker compose logs`, `bash scripts/detect_sdr.sh`
output, and your `.env` (redact anything sensitive) when filing an issue.
