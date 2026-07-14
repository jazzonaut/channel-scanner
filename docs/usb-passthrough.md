# USB passthrough (Linux)

To use a **real** RTL-SDR dongle from inside the Docker container you must (1)
let the host address the dongle without root and without the DVB driver holding
it, and (2) pass the USB device into the container. In simulation mode
(`SIMULATION_MODE=true`, the default) none of this is needed.

> RTL-SDR is **receive-only** here. Nothing below enables transmit.

## 1. Identify the dongle

```bash
lsusb | grep -Ei 'Realtek|RTL2838|0bda:2838'
# e.g. Bus 001 Device 004: ID 0bda:2838 Realtek Semiconductor Corp. RTL2838 DVB-T
```

Vendor `0bda` (Realtek), product `2838` (RTL2832U) is the common ID.

## 2. Free the dongle from the kernel DVB driver

Linux binds RTL2832U dongles to the DVB-T TV driver, which prevents SDR use
(`usb_claim_interface error -6`). Blacklist the DVB modules on the **host**:

```bash
sudo tee /etc/modprobe.d/blacklist-rtl.conf >/dev/null <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF

# Unload them now (or reboot):
sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
sudo modprobe -r rtl2832 2>/dev/null || true
```

Re-plug the dongle afterwards. Verify with `rtl_test -t` on the host.

## 3. udev rule for non-root access

By default USB device nodes are root-only. Add a host udev rule so your user
(and the container's non-root user) can open the device:

```bash
sudo tee /etc/udev/rules.d/99-rtl-sdr.rules >/dev/null <<'EOF'
# RTL-SDR (Realtek RTL2832U) — allow non-root access.
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", MODE="0666", GROUP="plugdev"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger
```

`MODE="0666"` grants world read/write on the node (simplest). If you prefer to
restrict to the `plugdev` group, drop the `0666` and add your user with
`sudo usermod -aG plugdev $USER` (log out/in), and set `group_add` in compose to
the host `plugdev` GID (`getent group plugdev`).

## 4. Pass the device into the container

The provided `docker-compose.yml` already does this **without** privileged mode:

```yaml
    devices:
      - /dev/bus/usb:/dev/bus/usb        # pass the whole USB bus
    device_cgroup_rules:
      - "c 189:* rmw"                     # allow USB char devices (major 189)
```

- `/dev/bus/usb:/dev/bus/usb` exposes USB device nodes to the container and
  survives re-plugging (the bus/dev numbers can change).
- `device_cgroup_rules: "c 189:* rmw"` authorizes the container cgroup to use
  **c**haracter devices with major number **189** (the USB bus devices) with
  **r**ead / **w**rite / **m**knod. Without this rule the node is visible but
  access is blocked.

### Map one specific device (optional, more locked down)

```yaml
    devices:
      - /dev/bus/usb/001/004:/dev/bus/usb/001/004   # from `lsusb` Bus/Device
```

Downside: the path changes when you re-plug, so `/dev/bus/usb` is usually better.

### Privileged fallback — last resort only

If, and only if, the above genuinely will not work on a restrictive host:

```yaml
    # privileged: true   # LAST RESORT — grants broad host device access, weakens
                         # isolation. Comment out devices:/device_cgroup_rules if used.
```

Do not run privileged as a default.

## 5. Verify inside the container

```bash
# Start the stack, then:
docker compose exec app lsusb | grep -Ei 'Realtek|RTL2838'
docker compose exec app rtl_test -t          # should enumerate the device
# The app also reports device status at:  GET http://localhost:8080/api/device
```

If `lsusb` shows the device on the host but not in the container, see
[troubleshooting.md](troubleshooting.md) → "USB visible on host but not in Docker".

## Notes for Docker Desktop (macOS / Windows)

USB passthrough to Linux containers is **not supported** by Docker Desktop's VM
in the standard configuration. On macOS/Windows, run the app in
`SIMULATION_MODE=true`, or run Docker on a native Linux host (or a Linux VM with
USB forwarding) for real-hardware capture.
