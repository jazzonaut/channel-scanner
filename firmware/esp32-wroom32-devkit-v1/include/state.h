// =============================================================================
//  state.h — shared, in-memory snapshot of what the ESP32 knows.
//
//  A single global instance (g_state) is written by the network/mock layer and
//  read by the Serial logger and the local web page. Single-threaded access
//  from loop() only, so no locking is required.
// =============================================================================
#pragma once
#include <Arduino.h>

struct MonitorState {
  // --- connectivity ---
  bool   wifiConnected   = false;
  bool   apMode          = false;      // true while running the config captive portal
  String ipAddress       = "0.0.0.0";  // STA IP, or SoftAP IP in AP mode
  bool   serverReachable = false;      // last REST poll succeeded

  // --- SDR / server status (mirrored from the backend) ---
  bool   sdrOnline       = false;      // health ok AND device available
  bool   simulation      = false;      // backend running in simulation mode
  String backend         = "unknown";  // "sim" | "rtlsdr" | "soapy" | "rtl_power"
  String deviceName      = "unknown";
  String serverVersion   = "unknown";
  float  uptimeS         = 0.0f;

  // --- scan configuration (from /api/config) ---
  long long scanStartHz  = 0;
  long long scanEndHz    = 0;

  // --- candidate channels (from /api/channels) ---
  int    activeChannels  = 0;          // status == "active"
  int    totalChannels   = 0;
  long long strongestHz  = 0;          // center_hz of strongest candidate
  float  strongestPowerDb = -999.0f;   // current_power_db of that candidate
  float  strongestSnrDb  = 0.0f;
  String lastDetectionIso = "";        // max last_seen across candidates (ISO 8601)

  // --- bookkeeping ---
  unsigned long lastSuccessMs = 0;     // millis() of last good poll / mock update
};

// Defined once in main.cpp.
extern MonitorState g_state;
