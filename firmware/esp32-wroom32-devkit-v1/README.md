# ESP32-WROOM-32 DevKit V1 — SDR Monitor Status Display (OPTIONAL)

A small, **optional** companion firmware for the
[`rtl-sdr-channel-detector`](../../) server. It runs on an
**ESP32-WROOM-32 DevKit V1** and shows the server's live status on the Serial
monitor and on a tiny built-in web page.

> **The ESP32 is a status display only.** A bare ESP32-WROOM-32 has **no
> sub-GHz radio** and **cannot receive or analyze 868 MHz** (or any RF) by
> itself. All spectrum and candidate-channel data comes from the RTL-SDR
> server; the ESP32 just mirrors it over Wi-Fi. See
> [Adding a local RF front-end](#optional-adding-a-local-868-mhz-front-end) for
> how an external transceiver *could* add local sensing later — it is never
> required.

## What it shows

Pulled from the server REST API (`/api/health`, `/api/device`, `/api/config`,
`/api/channels`):

- **SDR online/offline** (+ simulation flag, backend name)
- **Current scan range** (start .. end, in MHz)
- **Strongest detected candidate** frequency, power (dB) and SNR
- **Number of active candidate channels** (and total)
- **Last detection time** (max `last_seen`)
- Wi-Fi / server reachability and data age

Output goes to **Serial (115200)** and to a **web page served by the ESP32** on
your LAN (`http://<esp32-ip>/`).

## Project layout

```
firmware/esp32-wroom32-devkit-v1/
├── platformio.ini            # env:esp32dev, framework=arduino, deps
├── include/
│   ├── config.h              # compile-time config + feature toggles
│   ├── state.h               # shared MonitorState snapshot
│   ├── secrets.h.example      # template for Wi-Fi/server (copy -> secrets.h)
│   └── secrets.h             # YOUR creds (gitignored; you create this)
├── src/
│   ├── main.cpp              # setup/loop, web server, captive portal, mock
│   ├── net.cpp / net.h       # Wi-Fi state machine + REST polling
│   ├── display.cpp / display.h  # Serial status summary
│   └── webpage.h             # status + config HTML (PROGMEM)
├── data/                     # optional LittleFS assets (see data/README.md)
└── README.md
```

## 1. Install PlatformIO

Use the [PlatformIO IDE](https://platformio.org/install) (VS Code extension) or
the CLI:

```bash
pip install -U platformio
```

## 2. Configure Wi-Fi and the server

You have **three** options (checked in this order at runtime: NVS → secrets.h →
compile-time defaults):

**A) `secrets.h` (simplest for a personal build)**

```bash
cd firmware/esp32-wroom32-devkit-v1
cp include/secrets.h.example include/secrets.h
# edit include/secrets.h -> WIFI_SSID, WIFI_PASS, SERVER_HOST, SERVER_PORT
```

`include/secrets.h` is **gitignored** — never commit real credentials.

**B) Captive portal (no secrets.h needed)**

If no SSID is configured, or Wi-Fi fails repeatedly, the ESP32 starts an access
point:

- Join Wi-Fi **`ESP32-SDR-Monitor`** (password `sdrmonitor`, change it in
  `config.h`).
- A captive page opens (or browse to `http://192.168.4.1/`).
- Enter your Wi-Fi + server host/port, **Save & reboot**. Credentials are stored
  in NVS flash and survive reflashing the app.

> Prefer [WiFiManager](https://github.com/tzapu/WiFiManager)? It's a drop-in
> alternative to the built-in portal here. It's intentionally **not** a
> dependency so the firmware compiles with only the ESP32 core libraries.

**C) Compile-time defaults** — set `SERVER_HOST_DEFAULT` / `SERVER_PORT_DEFAULT`
in `include/config.h` or via `build_flags` in `platformio.ini`.

## 3. Find your serial port

The DevKit uses a USB-UART bridge (CP2102 or CH340). Plug it in, then:

| OS      | Typical port | How to find it |
|---------|--------------|----------------|
| Linux   | `/dev/ttyUSB0` (CP2102/CH340) or `/dev/ttyACM0` | `pio device list` or `ls /dev/ttyUSB* /dev/ttyACM*` |
| macOS   | `/dev/cu.usbserial-*` or `/dev/cu.SLAB_USBtoUART` (CP2102) / `/dev/cu.wchusbserial*` (CH340) | `pio device list` or `ls /dev/cu.*` |
| Windows | `COM3`, `COM5`, … | `pio device list` or Device Manager → Ports (COM & LPT) |

On Linux you may need dialout permissions: `sudo usermod -aG dialout $USER`
(log out/in). `platformio.ini` does **not** hard-code a port, so the toolchain
auto-detects; override only if needed (below).

## 4. Build

```bash
cd firmware/esp32-wroom32-devkit-v1
pio run                      # compile (env:esp32dev)
```

## 5. Upload

```bash
pio run -t upload                                  # auto-detect port
pio run -t upload --upload-port /dev/ttyUSB0       # Linux (explicit)
pio run -t upload --upload-port /dev/cu.SLAB_USBtoUART   # macOS (explicit)
pio run -t upload --upload-port COM5               # Windows (explicit)
```

If upload fails to sync, hold **BOOT**, tap **EN/RST**, release **BOOT** as it
starts (some clones need this).

## 6. Open the serial monitor

```bash
pio device monitor                     # auto-detect, 115200 (from platformio.ini)
pio device monitor -p /dev/ttyUSB0 -b 115200
```

You'll see a banner, then a status summary every few seconds. The log also
prints the ESP32's IP — open `http://<that-ip>/` in a browser for the web page.

Build + upload + monitor in one go:

```bash
pio run -t upload && pio device monitor
```

## MOCK_MODE — run with no server

`MOCK_MODE` fabricates plausible data so you can try the firmware/UI **without a
running server** (great on the bench):

```bash
pio run -D MOCK_MODE=1 -t upload && pio device monitor
```

Or uncomment `-D MOCK_MODE=1` in `platformio.ini` (or set `#define MOCK_MODE 1`
in `config.h`). In MOCK_MODE the ESP32 still joins Wi-Fi (so the web page is
reachable) but does **not** contact any server — a synthetic candidate wanders
around 868.3 MHz and the channel counts breathe. Timestamps are clearly marked
`(mock)`.

## Behaviour / reliability

- **Non-blocking**: `loop()` is a `millis()`-based state machine; no `delay()`
  in the hot path. HTTP GETs use short timeouts to stay responsive.
- **Auto-reconnect with backoff**: Wi-Fi drops are re-connected; repeated
  connect failures fall back to the config portal. Server-poll failures back off
  exponentially (3 s → 30 s cap) and recover automatically.
- **No hardcoded credentials**: real Wi-Fi/server values live only in the
  gitignored `secrets.h` or in NVS via the portal.

## Optional: adding a local 868 MHz front-end

The bare ESP32 cannot sense RF. If you later want *local* sub-GHz sensing
(independent of the server), add an external SPI transceiver and set
`FEATURE_RF_FRONTEND=1` in `config.h`. Candidate modules:

| Module | Bus | Notes |
|--------|-----|-------|
| CC1101 | SPI | Sub-GHz ISM, RSSI + OOK/2-FSK packet RX |
| SX1276 / RFM95 | SPI | LoRa/FSK, RSSI + SNR |
| RFM69  | SPI | FSK, RSSI |

Suggested wiring on the VSPI bus: `SCK=18, MISO=19, MOSI=23, CS=5`, plus a free
GPIO for the module's `GDOx`/`DIOx` interrupt. This is future work — the
firmware compiles and runs fully without any of it, and the ESP32 remains a
receive-only *status mirror* of the RTL-SDR server.

## Troubleshooting

- **Web page shows "NO SERVER"**: check `SERVER_HOST`/`SERVER_PORT`, that the
  backend is up (`curl http://<host>:8080/api/health`), and that the ESP32 and
  server are on the same reachable network.
- **Stuck in AP mode**: wrong Wi-Fi password, or SSID out of range. Reconnect to
  `ESP32-SDR-Monitor` and re-enter details.
- **Garbled serial**: set the monitor baud to **115200**.
