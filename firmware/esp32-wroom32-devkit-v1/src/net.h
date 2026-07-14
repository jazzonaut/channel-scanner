// =============================================================================
//  net.h — Wi-Fi lifecycle + REST polling of the rtl-sdr-channel-detector API.
//
//  Non-blocking: netLoop() drives a small state machine (connecting / online /
//  AP config portal). It never calls delay(). HTTP GETs use short timeouts so a
//  single loop() iteration stays responsive.
// =============================================================================
#pragma once
#include <Arduino.h>

// Initialise Wi-Fi (loads creds from NVS -> secrets.h -> config defaults) and
// begin connecting, or start the AP config portal if no SSID is known.
void netBegin();

// Pump the Wi-Fi state machine and (when online, non-mock) poll the server.
// Call every loop() iteration.
void netLoop();

// True while the config captive portal (SoftAP) is active.
bool netInApMode();

// Base URL of the target server, e.g. "http://192.168.1.50:8080".
String netServerBase();

// Persist Wi-Fi + server config to NVS (used by the captive portal form).
// Does NOT reboot; the caller decides when to restart.
void netSaveConfig(const String& ssid, const String& pass,
                   const String& host, uint16_t port);
