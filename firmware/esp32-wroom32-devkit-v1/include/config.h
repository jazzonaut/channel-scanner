// =============================================================================
//  config.h — compile-time configuration for the ESP32 status display
//
//  Everything here is a *default*. Wi-Fi credentials and the server target can
//  also be supplied at runtime via:
//    1) include/secrets.h  (copied from secrets.h.example, gitignored), or
//    2) the built-in captive portal (AP mode), which stores them in NVS.
//  Runtime values (NVS, then secrets.h) take precedence over these defaults.
// =============================================================================
#pragma once

// Pull in local Wi-Fi / server secrets if the developer created them.
// secrets.h is gitignored; secrets.h.example documents the format.
#if __has_include("secrets.h")
  #include "secrets.h"
#endif

// -----------------------------------------------------------------------------
//  Server (rtl-sdr-channel-detector backend) target defaults
//  Backend default port is 8080 per the shared CONTRACT (WEB_PORT).
//  These are only used if secrets.h / NVS do not provide a host/port.
// -----------------------------------------------------------------------------
#ifndef SERVER_HOST_DEFAULT
  #define SERVER_HOST_DEFAULT "192.168.1.50"   // <-- change to your server IP/host
#endif
#ifndef SERVER_PORT_DEFAULT
  #define SERVER_PORT_DEFAULT 8080
#endif

// -----------------------------------------------------------------------------
//  Polling behaviour (REST client)
// -----------------------------------------------------------------------------
#define POLL_INTERVAL_MS         3000    // steady-state poll cadence
#define HTTP_CONNECT_TIMEOUT_MS  2000    // keep small so loop() stays responsive
#define HTTP_TIMEOUT_MS          3000    // per-request read timeout
#define POLL_BACKOFF_START_MS    3000    // first backoff step after a failure
#define POLL_BACKOFF_MAX_MS      30000   // cap for exponential backoff

// -----------------------------------------------------------------------------
//  Wi-Fi / captive portal
// -----------------------------------------------------------------------------
#define WIFI_CONNECT_TIMEOUT_MS  15000   // per connect attempt before retry
#define WIFI_RETRY_BEFORE_AP     3       // failed cycles before AP config mode
#define AP_SSID                  "ESP32-SDR-Monitor"
#define AP_PASSWORD              "sdrmonitor"   // >= 8 chars; CHANGE ME
// NOTE: WiFiManager (tzapu/WiFiManager) is a drop-in alternative to the small
//       captive portal implemented here. It is intentionally NOT a dependency
//       so the firmware compiles with only the built-in ESP32 libraries.

// -----------------------------------------------------------------------------
//  Local status web server (served BY the ESP32, on your LAN)
// -----------------------------------------------------------------------------
#define WEB_SERVER_PORT          80
#define STATE_JSON_PATH          "/state.json"

// -----------------------------------------------------------------------------
//  Serial logging
// -----------------------------------------------------------------------------
#define SERIAL_BAUD              115200
#define SERIAL_STATUS_INTERVAL_MS 5000   // periodic status summary to Serial

// -----------------------------------------------------------------------------
//  MOCK_MODE — fabricate plausible data so the firmware runs with NO server.
//  Enable via build flag (-D MOCK_MODE=1) or by changing the default below.
// -----------------------------------------------------------------------------
#ifndef MOCK_MODE
  #define MOCK_MODE 0
#endif
#define MOCK_UPDATE_INTERVAL_MS  1000

// -----------------------------------------------------------------------------
//  Feature toggles
// -----------------------------------------------------------------------------
#define FEATURE_WEB_UI           1       // serve the local status web page
#define FEATURE_SERIAL_LOG       1       // periodic Serial status summary
#ifndef FEATURE_WEBSOCKET
  #define FEATURE_WEBSOCKET      0       // reserved: use WS /ws/live vs REST poll
#endif

// -----------------------------------------------------------------------------
//  OPTIONAL local 868 MHz RF front-end (NOT required, NOT present by default)
//
//  The bare ESP32-WROOM-32 has NO sub-GHz radio and CANNOT receive or analyze
//  868 MHz on its own. If you later add an external transceiver module you can
//  do *local* RF sensing in addition to mirroring the server. Candidates:
//    - CC1101   (SPI, sub-GHz ISM, RSSI + packet/OOK)
//    - SX1276 / RFM95 (LoRa/FSK, SPI, RSSI/SNR)
//    - RFM69    (FSK, SPI, RSSI)
//  Wire it on the VSPI bus (SCK=18, MISO=19, MOSI=23, CS=5, GDOx/DIO -> a free
//  GPIO for interrupts) and set FEATURE_RF_FRONTEND=1. This is future work; the
//  firmware compiles and runs fully without it.
// -----------------------------------------------------------------------------
#ifndef FEATURE_RF_FRONTEND
  #define FEATURE_RF_FRONTEND    0
#endif
