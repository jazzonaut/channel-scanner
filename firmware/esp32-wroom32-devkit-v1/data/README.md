# `data/` — filesystem image (LittleFS/SPIFFS)

This directory holds files that get flashed to the ESP32's on-board filesystem
(LittleFS or SPIFFS) as a separate image from the program. PlatformIO builds and
uploads it with the filesystem targets:

```bash
pio run -t buildfs      # build the filesystem image from data/
pio run -t uploadfs     # flash it to the ESP32
```

## Current status

The shipped firmware does **not require** any filesystem assets — the status
web page and config page are compiled into flash as PROGMEM strings
(`src/webpage.h`), so the firmware runs with an empty `data/` directory. This
folder exists as the conventional home for optional assets.

## What you might put here later

- `index.html` / CSS / JS if you move the web UI out of PROGMEM and serve it
  from LittleFS (nice for iterating on the UI without recompiling C++).
- A JSON config/defaults file.
- Small icons or a favicon.

If you add files here, also add the LittleFS dependency and (optionally) set
`board_build.filesystem = littlefs` in `platformio.ini`, then serve them with
`server.serveStatic(...)` or `LittleFS.open(...)` in `src/main.cpp`.

> This file is intentionally kept minimal; it is safe to leave `data/` otherwise
> empty.
