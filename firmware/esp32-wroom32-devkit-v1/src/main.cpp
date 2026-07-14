// =============================================================================
//  main.cpp — ESP32-WROOM-32 DevKit V1 companion firmware
//
//  OPTIONAL status display for the rtl-sdr-channel-detector server.
//
//  IMPORTANT: The ESP32 is a *status display only*. A bare ESP32-WROOM-32 has
//  NO sub-GHz radio and CANNOT receive or analyze 868 MHz (or any RF) on its
//  own. All spectrum/candidate data shown here is produced by the RTL-SDR
//  server; the ESP32 merely mirrors it over Wi-Fi. (See config.h for how an
//  external CC1101/SX1276/RFM69 could add OPTIONAL local RF sensing later.)
//
//  Design:
//   - Fully non-blocking loop() (millis()-based); no delay() in the hot path.
//   - Wi-Fi: connect from secrets.h/NVS with auto-reconnect + backoff, or fall
//     back to an AP captive portal to enter credentials (net.cpp).
//   - REST polling of /api/health, /api/device, /api/config, /api/channels
//     (net.cpp), parsed with ArduinoJson v7.
//   - Serial status summary (display.cpp) + a small local web page (this file).
//   - MOCK_MODE (compile-time) fabricates plausible data so it runs offline.
//
//  Compile-time configuration examples:
//    pio run -e esp32dev                              # LIVE, uses secrets.h/portal
//    pio run -e esp32dev -D MOCK_MODE=1               # offline demo, fake data
//    pio run -e esp32dev \
//       -D SERVER_HOST_DEFAULT='"10.0.0.5"' -D SERVER_PORT_DEFAULT=8080
// =============================================================================
#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <ArduinoJson.h>

#include "config.h"
#include "state.h"
#include "net.h"
#include "display.h"
#include "webpage.h"

// The single shared status snapshot (declared extern in state.h).
MonitorState g_state;

static WebServer  server(WEB_SERVER_PORT);
static DNSServer  dnsServer;
static bool       s_dnsStarted = false;

// Deferred reboot (set by the config form; executed in loop() to avoid delay()).
static unsigned long s_rebootAt = 0;

// -----------------------------------------------------------------------------
//  MOCK data generator (only compiled in when MOCK_MODE=1)
// -----------------------------------------------------------------------------
#if MOCK_MODE
static void mockUpdate() {
  static unsigned long last = 0;
  if (millis() - last < MOCK_UPDATE_INTERVAL_MS) return;
  last = millis();

  const float t = millis() / 1000.0f;

  g_state.serverReachable = true;
  g_state.sdrOnline       = true;
  g_state.simulation      = true;
  g_state.backend         = "sim";
  g_state.deviceName      = "Mock RTL-SDR (simulation)";
  g_state.serverVersion   = "mock-0.0.0";
  g_state.uptimeS         = t;

  // 868 MHz ISM band region, matching the contract's default scan window.
  g_state.scanStartHz = 867000000LL;
  g_state.scanEndHz   = 870000000LL;

  // A candidate that slowly wanders around 868.3 MHz with a breathing level.
  g_state.strongestHz      = 868300000LL + (long long)(sinf(t * 0.20f) * 150000.0f);
  g_state.strongestPowerDb = -42.0f + sinf(t * 0.50f) * 6.0f;
  g_state.strongestSnrDb   = 18.0f + sinf(t * 0.30f) * 4.0f;

  g_state.activeChannels = 3 + (int)((sinf(t * 0.10f) + 1.0f) * 2.0f);  // 3..7
  g_state.totalChannels  = g_state.activeChannels + 5;

  // Fabricated ISO-ish timestamp (no RTC/NTP in mock); clearly marked.
  char buf[40];
  unsigned long secs = (unsigned long)t;
  snprintf(buf, sizeof(buf), "2026-07-14T12:%02lu:%02luZ (mock)",
           (secs / 60) % 60, secs % 60);
  g_state.lastDetectionIso = buf;

  g_state.lastSuccessMs = millis();
}
#endif

// -----------------------------------------------------------------------------
//  Web handlers
// -----------------------------------------------------------------------------
static void handleRoot() {
  if (netInApMode()) {
    server.send_P(200, "text/html", CONFIG_PAGE_HTML);
  } else {
    server.send_P(200, "text/html", STATUS_PAGE_HTML);
  }
}

// Serialize g_state to JSON for the status page's fetch() loop.
static void handleStateJson() {
  JsonDocument doc;
  doc["wifiConnected"]   = g_state.wifiConnected;
  doc["apMode"]          = g_state.apMode;
  doc["ip"]              = g_state.ipAddress;
  doc["serverReachable"] = g_state.serverReachable;
  doc["sdrOnline"]       = g_state.sdrOnline;
  doc["simulation"]      = g_state.simulation;
  doc["backend"]         = g_state.backend;
  doc["deviceName"]      = g_state.deviceName;
  doc["serverVersion"]   = g_state.serverVersion;
  doc["uptimeS"]         = g_state.uptimeS;
  doc["scanStartHz"]     = g_state.scanStartHz;
  doc["scanEndHz"]       = g_state.scanEndHz;
  doc["activeChannels"]  = g_state.activeChannels;
  doc["totalChannels"]   = g_state.totalChannels;
  doc["strongestHz"]     = g_state.strongestHz;
  doc["strongestPowerDb"]= g_state.strongestPowerDb;
  doc["strongestSnrDb"]  = g_state.strongestSnrDb;
  doc["lastDetectionIso"]= g_state.lastDetectionIso;
  doc["ageMs"]           = (g_state.lastSuccessMs == 0)
                             ? 0UL : (millis() - g_state.lastSuccessMs);
#if MOCK_MODE
  doc["mock"] = true;
#else
  doc["mock"] = false;
#endif

  String out;
  serializeJson(doc, out);
  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "application/json", out);
}

// Config form POST -> save to NVS -> schedule reboot.
static void handleSave() {
  String ssid = server.arg("ssid");
  String pass = server.arg("pass");
  String host = server.arg("host");
  uint16_t port = (uint16_t)server.arg("port").toInt();

  if (ssid.length() == 0) {
    server.send(400, "text/plain", "SSID is required");
    return;
  }
  netSaveConfig(ssid, pass, host, port);
  server.send(200, "text/html",
              "<meta charset=utf-8><body style='font-family:sans-serif;background:#0e1116;color:#e6edf3'>"
              "<h3>Saved. Rebooting&hellip;</h3>"
              "<p>Reconnect to your normal Wi-Fi; the device will join it shortly.</p></body>");
  s_rebootAt = millis() + 1200;   // deferred restart, no delay() here
}

static void handleNotFound() {
  // In AP mode, redirect everything to the config page (captive-portal UX).
  if (netInApMode()) {
    server.sendHeader("Location", String("http://") + WiFi.softAPIP().toString() + "/");
    server.send(302, "text/plain", "");
  } else {
    server.send(404, "text/plain", "Not found");
  }
}

static void startWebServer() {
  server.on("/", HTTP_GET, handleRoot);
  server.on(STATE_JSON_PATH, HTTP_GET, handleStateJson);
  server.on("/save", HTTP_POST, handleSave);
  server.onNotFound(handleNotFound);
  server.begin();
  Serial.printf("[web] Status server on port %d\n", WEB_SERVER_PORT);
}

// -----------------------------------------------------------------------------
//  Arduino entry points
// -----------------------------------------------------------------------------
void setup() {
  Serial.begin(SERIAL_BAUD);
  // Brief, bounded wait for the USB-CDC/serial to come up (not in loop()).
  unsigned long t0 = millis();
  while (!Serial && (millis() - t0 < 1500)) { /* spin briefly */ }

  displayBegin();
  netBegin();

#if FEATURE_WEB_UI
  startWebServer();
#endif
}

void loop() {
  // 1) Wi-Fi state machine + REST polling (skipped for polling in MOCK_MODE).
  netLoop();

  // 2) Captive-portal DNS: only while the AP config portal is active.
  if (netInApMode()) {
    if (!s_dnsStarted) {
      dnsServer.start(53, "*", WiFi.softAPIP());   // resolve every host -> ESP
      s_dnsStarted = true;
    }
    dnsServer.processNextRequest();
  } else if (s_dnsStarted) {
    dnsServer.stop();
    s_dnsStarted = false;
  }

  // 3) Fabricate data when built in MOCK_MODE.
#if MOCK_MODE
  mockUpdate();
#endif

  // 4) Serve the local web UI.
#if FEATURE_WEB_UI
  server.handleClient();
#endif

  // 5) Periodic Serial status summary.
  displayTick();

  // 6) Deferred reboot (after saving config via the portal).
  if (s_rebootAt != 0 && millis() >= s_rebootAt) {
    Serial.println("[sys] Rebooting to apply new configuration...");
    Serial.flush();
    ESP.restart();
  }

  // No delay() — yield cooperatively to the RTOS/Wi-Fi stack.
  yield();
}
