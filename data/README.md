# `data/` — runtime data (gitignored)

This directory is mounted into the container at `/data`. Its **contents are
gitignored** (only `.gitkeep` and this README are tracked) — nothing here should
be committed.

## Subdirectories

- `db/` — SQLite database (`channel_detector.sqlite3`) holding sessions,
  detections, candidate channels, events and recording metadata. Path is set by
  `DATABASE_PATH` (default `/data/db/channel_detector.sqlite3`).
- `recordings/` — IQ recordings and their SigMF-style metadata, written only
  when `ENABLE_IQ_RECORDING=true`. Bounded by `MAX_IQ_STORAGE_GB`. Path is set
  by `RECORDING_PATH` (default `/data/recordings`).
- `logs/` — application log files.

These directories are created by `scripts/bootstrap.sh` (and by the container on
first run).

## Resetting

To wipe DB, recordings and logs while keeping the directories:

```bash
bash scripts/reset_data.sh   # or: make reset-data
```

Old rows and files are also pruned automatically per `RETENTION_DAYS` and
`MAX_IQ_STORAGE_GB`.
