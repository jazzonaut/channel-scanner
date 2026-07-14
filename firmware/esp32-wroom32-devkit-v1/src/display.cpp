// =============================================================================
//  display.cpp — Serial status summary. See display.h.
// =============================================================================
#include "display.h"
#include "config.h"
#include "state.h"

static unsigned long s_lastPrint = 0;

// Format an integer-Hz value as a human MHz string, e.g. 868300000 -> "868.300 MHz".
static String fmtMHz(long long hz) {
  if (hz <= 0) return String("--");
  double mhz = (double)hz / 1e6;
  char buf[24];
  snprintf(buf, sizeof(buf), "%.3f MHz", mhz);
  return String(buf);
}

void displayBegin() {
  Serial.println();
  Serial.println("==========================================================");
  Serial.println("  ESP32-WROOM-32 — rtl-sdr-channel-detector STATUS DISPLAY");
  Serial.println("  (receive-only monitor mirror; ESP32 does NOT receive RF)");
#if MOCK_MODE
  Serial.println("  MODE: MOCK  (fabricated data, no server required)");
#else
  Serial.println("  MODE: LIVE  (polls server REST API over Wi-Fi)");
#endif
  Serial.println("==========================================================");
}

void displayTick() {
#if FEATURE_SERIAL_LOG
  if (millis() - s_lastPrint < SERIAL_STATUS_INTERVAL_MS) return;
  s_lastPrint = millis();

  const MonitorState& s = g_state;

  unsigned long ageMs = (s.lastSuccessMs == 0) ? 0 : (millis() - s.lastSuccessMs);

  Serial.println("----------------------------------------------------------");
  Serial.printf ("  Wi-Fi     : %s  IP %s%s\n",
                 s.wifiConnected ? "CONNECTED" : (s.apMode ? "AP-CONFIG" : "DOWN"),
                 s.ipAddress.c_str(),
                 s.apMode ? "  (config portal)" : "");
  Serial.printf ("  Server    : %s  v%s  up %.0fs\n",
                 s.serverReachable ? "reachable" : "UNREACHABLE",
                 s.serverVersion.c_str(), s.uptimeS);
  Serial.printf ("  SDR       : %s%s  backend=%s  (%s)\n",
                 s.sdrOnline ? "ONLINE" : "OFFLINE",
                 s.simulation ? " [SIM]" : "",
                 s.backend.c_str(), s.deviceName.c_str());
  Serial.printf ("  Scan range: %s .. %s\n",
                 fmtMHz(s.scanStartHz).c_str(), fmtMHz(s.scanEndHz).c_str());
  Serial.printf ("  Channels  : %d active / %d total\n",
                 s.activeChannels, s.totalChannels);
  if (s.strongestPowerDb > -900.0f && s.strongestHz > 0) {
    Serial.printf ("  Strongest : %s  %.1f dB  (SNR %.1f dB)\n",
                   fmtMHz(s.strongestHz).c_str(),
                   s.strongestPowerDb, s.strongestSnrDb);
  } else {
    Serial.println("  Strongest : --");
  }
  Serial.printf ("  Last det. : %s\n",
                 s.lastDetectionIso.length() ? s.lastDetectionIso.c_str() : "--");
  Serial.printf ("  Data age  : %lu ms\n", ageMs);
  Serial.println("----------------------------------------------------------");
#endif
}
