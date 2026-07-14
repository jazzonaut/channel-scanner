// =============================================================================
//  display.h — Serial "display" for the status snapshot.
//
//  The ESP32-WROOM-32 DevKit V1 has no on-board screen, so the primary local
//  output is the Serial monitor (115200 baud). If you add an SSD1306 / TFT you
//  can render g_state here too. displayTick() is rate-limited internally.
// =============================================================================
#pragma once
#include <Arduino.h>

void displayBegin();     // print a one-time banner
void displayTick();      // periodic, rate-limited status summary to Serial
