# rtl-sdr-channel-detector — backend

Receive-only RTL-SDR passive spectrum monitoring backend (FastAPI, Python 3.12).
It scans a frequency band, estimates a noise floor, detects occupied regions,
clusters them into **candidate channels** (inferred occupied spectrum regions —
*not* official/licensed protocol channels), tracks recurrence, and streams
reduced spectrum frames + channel/event updates to browsers over WebSocket.

**This project is strictly receive-only. It never transmits, replays, jams, or
spoofs. Unknown payloads are treated as opaque binary and never decoded past
what is plainly receivable in the clear.**

## Run (simulation, zero hardware)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
SIMULATION_MODE=true DATABASE_PATH=./data/db.sqlite3 \
  LOG_DIR=./data/logs RECORDING_PATH=./data/rec \
  uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Open http://localhost:8080/api/docs for the OpenAPI UI, or http://localhost:8080/
for the served frontend shell. Live updates: `ws://localhost:8080/ws/live`.

## Configuration

All settings come from environment variables (see `app/config.py` and the shared
`CONTRACT.md`). Key ones: `SDR_BACKEND` (`sim|rtlsdr|soapy|rtl_power`),
`SCAN_START_HZ`, `SCAN_END_HZ`, `DETECTION_THRESHOLD_DB`, `NOISE_FLOOR_ALPHA`,
`FFT_SIZE`, `SPECTRUM_FPS`, `SPECTRUM_BINS`, `ENABLE_IQ_RECORDING`,
`MAX_IQ_STORAGE_GB`, `RETENTION_DAYS`.

The app auto-falls back to the simulator when hardware/libraries are missing.

## Optional hardware / tools

- Real dongle: `pip install '.[rtlsdr]'` (needs `librtlsdr`), set `SDR_BACKEND=rtlsdr`.
- Sweep mode: `rtl_power` on PATH, `SDR_BACKEND=rtl_power`.
- Passive labelling: `rtl_433` on PATH enables opportunistic decode of
  plainly-receivable, unencrypted telemetry (disabled if the binary is absent).

## Layout

```
app/
  api/               REST routers (health, metrics, device, config, scan,
                     channels, events, sessions, export, recordings, clients,
                     control) aggregated under /api
  sdr/               backend abstraction: base ABC, sim, rtlsdr, rtl_power, factory
  signal_processing/ noise_floor, psd, detector, clustering, recurrence, fingerprint
  services/          scan_manager (core), control_lease, recorder, decoder, retention
  storage/           db (aiosqlite/WAL), migrations, repositories
  models/            pydantic v2 schemas
  websocket/         hub + /ws/live route
tests/               pytest (async) against the simulator, no hardware needed
```

## Tests

```bash
cd backend
pip install -r requirements.txt   # includes httpx/pytest/pytest-asyncio
pytest
```

Tests run entirely in `SIMULATION_MODE=true` with an in-memory / temp SQLite DB.
