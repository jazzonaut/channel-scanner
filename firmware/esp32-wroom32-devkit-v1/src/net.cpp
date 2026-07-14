// =============================================================================
//  net.cpp — Wi-Fi state machine + REST polling. See net.h.
// =============================================================================
#include "net.h"
#include "config.h"
#include "state.h"

#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <ArduinoJson.h>

// -----------------------------------------------------------------------------
//  Internal state
// -----------------------------------------------------------------------------
enum NetMode { NM_CONNECTING, NM_ONLINE, NM_AP };
static NetMode       s_mode          = NM_CONNECTING;
static unsigned long s_connectStart  = 0;
static int           s_failCycles    = 0;

// Effective config (NVS -> secrets.h -> compile-time defaults).
static String        s_ssid;
static String        s_pass;
static String        s_host;
static uint16_t      s_port          = 0;

// Poll scheduling / backoff.
static unsigned long s_lastPollMs    = 0;
static unsigned long s_pollInterval  = POLL_INTERVAL_MS;

static Preferences   s_prefs;
static const char*   PREFS_NS        = "sdrmon";

// -----------------------------------------------------------------------------
//  Config load / save
// -----------------------------------------------------------------------------
static void loadConfig() {
  s_prefs.begin(PREFS_NS, /*readOnly=*/true);
  s_ssid = s_prefs.getString("ssid", "");
  s_pass = s_prefs.getString("pass", "");
  s_host = s_prefs.getString("host", "");
  s_port = s_prefs.getUShort("port", 0);
  s_prefs.end();

  // Fall back to secrets.h (if present) for Wi-Fi.
#ifdef WIFI_SSID
  if (s_ssid.length() == 0) {
    s_ssid = WIFI_SSID;
    s_pass = WIFI_PASS;
  }
#endif

  // Fall back to secrets.h then config defaults for the server target.
  if (s_host.length() == 0) {
#ifdef SERVER_HOST
    s_host = SERVER_HOST;
#else
    s_host = SERVER_HOST_DEFAULT;
#endif
  }
  if (s_port == 0) {
#ifdef SERVER_PORT
    s_port = SERVER_PORT;
#else
    s_port = SERVER_PORT_DEFAULT;
#endif
  }
}

void netSaveConfig(const String& ssid, const String& pass,
                   const String& host, uint16_t port) {
  s_prefs.begin(PREFS_NS, /*readOnly=*/false);
  s_prefs.putString("ssid", ssid);
  s_prefs.putString("pass", pass);
  if (host.length()) s_prefs.putString("host", host);
  if (port)          s_prefs.putUShort("port", port);
  s_prefs.end();
  Serial.printf("[net] Saved config to NVS (ssid='%s', host='%s:%u')\n",
                ssid.c_str(), host.c_str(), (unsigned)port);
}

String netServerBase() {
  return String("http://") + s_host + ":" + String((unsigned)s_port);
}

bool netInApMode() { return s_mode == NM_AP; }

// -----------------------------------------------------------------------------
//  Mode transitions
// -----------------------------------------------------------------------------
static void startConnect() {
  s_mode = NM_CONNECTING;
  s_connectStart = millis();
  g_state.wifiConnected = false;
  g_state.apMode = false;
  WiFi.mode(WIFI_STA);
  WiFi.begin(s_ssid.c_str(), s_pass.c_str());
  Serial.printf("[net] Connecting to Wi-Fi SSID '%s' ...\n", s_ssid.c_str());
}

static void startAp() {
  s_mode = NM_AP;
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASSWORD);
  IPAddress ip = WiFi.softAPIP();
  g_state.apMode = true;
  g_state.wifiConnected = false;
  g_state.ipAddress = ip.toString();
  Serial.println("[net] ------------------------------------------------------");
  Serial.printf ("[net] Config portal up. Join Wi-Fi '%s' (pass '%s')\n",
                 AP_SSID, AP_PASSWORD);
  Serial.printf ("[net] Then browse to http://%s/  to set credentials.\n",
                 ip.toString().c_str());
  Serial.println("[net] ------------------------------------------------------");
}

void netBegin() {
  loadConfig();
  if (s_ssid.length() == 0) {
    Serial.println("[net] No Wi-Fi SSID configured -> starting config portal.");
    startAp();
  } else {
    startConnect();
  }
}

// -----------------------------------------------------------------------------
//  HTTP helper: GET `path` and parse JSON into `doc`. Optional streaming filter.
// -----------------------------------------------------------------------------
static bool httpGetJson(const char* path, JsonDocument& doc,
                        JsonDocument* filter = nullptr) {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;
  String url = netServerBase() + String(path);
  http.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  http.setReuse(false);
  if (!http.begin(url)) {
    Serial.printf("[net] http.begin() failed for %s\n", url.c_str());
    return false;
  }
  http.setTimeout(HTTP_TIMEOUT_MS);

  int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.printf("[net] GET %s -> HTTP %d\n", path, code);
    http.end();
    return false;
  }

  DeserializationError err;
  if (filter) {
    err = deserializeJson(doc, http.getStream(),
                          DeserializationOption::Filter(*filter));
  } else {
    err = deserializeJson(doc, http.getStream());
  }
  http.end();

  if (err) {
    Serial.printf("[net] JSON parse error on %s: %s\n", path, err.c_str());
    return false;
  }
  return true;
}

// -----------------------------------------------------------------------------
//  Poll bookkeeping
// -----------------------------------------------------------------------------
static void onPollSuccess() {
  s_pollInterval = POLL_INTERVAL_MS;                 // reset backoff
  g_state.serverReachable = true;
  g_state.lastSuccessMs = millis();
}

static void onPollFail() {
  g_state.serverReachable = false;
  g_state.sdrOnline = false;
  // Exponential backoff, capped.
  unsigned long next = s_pollInterval * 2;
  if (next < POLL_BACKOFF_START_MS) next = POLL_BACKOFF_START_MS;
  if (next > POLL_BACKOFF_MAX_MS)   next = POLL_BACKOFF_MAX_MS;
  s_pollInterval = next;
  Serial.printf("[net] Poll failed; backing off to %lu ms\n", s_pollInterval);
}

// -----------------------------------------------------------------------------
//  One full poll cycle across the relevant REST endpoints.
// -----------------------------------------------------------------------------
static void pollServer() {
  JsonDocument doc;

  // --- /api/health --------------------------------------------------------
  if (!httpGetJson("/api/health", doc)) { onPollFail(); return; }
  bool healthOk = (String((const char*)(doc["status"] | "")) == "ok");
  g_state.simulation    = doc["simulation"] | false;
  g_state.uptimeS       = doc["uptime_s"]   | 0.0f;
  g_state.serverVersion = (const char*)(doc["version"] | "unknown");

  // --- /api/device --------------------------------------------------------
  bool deviceAvailable = false;
  doc.clear();
  if (httpGetJson("/api/device", doc)) {
    deviceAvailable   = doc["available"] | false;
    g_state.backend    = (const char*)(doc["backend"] | "unknown");
    g_state.deviceName = (const char*)(doc["name"]    | "unknown");
    // In simulation, the "device" is available but synthetic.
    if (doc["simulation"].is<bool>()) g_state.simulation = doc["simulation"] | false;
  }

  // --- /api/config --------------------------------------------------------
  doc.clear();
  if (httpGetJson("/api/config", doc)) {
    g_state.scanStartHz = doc["start_hz"] | 0LL;
    g_state.scanEndHz   = doc["end_hz"]   | 0LL;
  }

  // --- /api/channels (filtered stream to save RAM) ------------------------
  doc.clear();
  {
    // Only pull the fields we display. The filter for an array is an array with
    // a single element describing each item (ArduinoJson v7 streaming filter).
    JsonDocument filter;
    filter["channels"][0]["center_hz"]        = true;
    filter["channels"][0]["current_power_db"] = true;
    filter["channels"][0]["snr_db"]           = true;
    filter["channels"][0]["status"]           = true;
    filter["channels"][0]["last_seen"]        = true;

    if (httpGetJson("/api/channels", doc, &filter)) {
      int   active = 0, total = 0;
      long long strongestHz = 0;
      float strongestPow = -999.0f, strongestSnr = 0.0f;
      String lastSeen = "";

      JsonArray arr = doc["channels"].as<JsonArray>();
      for (JsonObject ch : arr) {
        total++;
        const char* st = ch["status"] | "";
        if (strcmp(st, "active") == 0) active++;

        float p = ch["current_power_db"] | -999.0f;
        if (p > strongestPow) {
          strongestPow  = p;
          strongestHz   = ch["center_hz"] | 0LL;
          strongestSnr  = ch["snr_db"]    | 0.0f;
        }

        const char* ls = ch["last_seen"] | "";
        // ISO 8601 UTC strings sort lexically == chronologically.
        if (strlen(ls) && String(ls) > lastSeen) lastSeen = String(ls);
      }

      g_state.totalChannels    = total;
      g_state.activeChannels   = active;
      g_state.strongestHz      = strongestHz;
      g_state.strongestPowerDb = strongestPow;
      g_state.strongestSnrDb   = strongestSnr;
      if (lastSeen.length()) g_state.lastDetectionIso = lastSeen;
    }
  }

  // Overall SDR "online" = backend healthy AND a device is available.
  g_state.sdrOnline = healthOk && deviceAvailable;
  onPollSuccess();
}

// -----------------------------------------------------------------------------
//  Main pump
// -----------------------------------------------------------------------------
void netLoop() {
  switch (s_mode) {
    case NM_CONNECTING:
      if (WiFi.status() == WL_CONNECTED) {
        s_mode = NM_ONLINE;
        s_failCycles = 0;
        s_lastPollMs = 0;                      // poll immediately
        s_pollInterval = POLL_INTERVAL_MS;
        g_state.wifiConnected = true;
        g_state.apMode = false;
        g_state.ipAddress = WiFi.localIP().toString();
        Serial.printf("[net] Wi-Fi connected. IP: %s\n",
                      g_state.ipAddress.c_str());
      } else if (millis() - s_connectStart > WIFI_CONNECT_TIMEOUT_MS) {
        s_failCycles++;
        Serial.printf("[net] Wi-Fi connect timeout (cycle %d/%d)\n",
                      s_failCycles, WIFI_RETRY_BEFORE_AP);
        if (s_failCycles >= WIFI_RETRY_BEFORE_AP) {
          startAp();                            // give up -> config portal
        } else {
          WiFi.disconnect();
          startConnect();                       // retry
        }
      }
      break;

    case NM_ONLINE:
      if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[net] Wi-Fi lost -> reconnecting.");
        g_state.wifiConnected = false;
        g_state.serverReachable = false;
        g_state.sdrOnline = false;
        startConnect();
        break;
      }
#if MOCK_MODE == 0
      if (millis() - s_lastPollMs >= s_pollInterval) {
        s_lastPollMs = millis();
        pollServer();
      }
#endif
      break;

    case NM_AP:
      // Stay in the portal until the user saves credentials (main.cpp reboots).
      break;
  }
}
