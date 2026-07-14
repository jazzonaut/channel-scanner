"""Versioned schema migrations, applied on startup.

Uses PRAGMA user_version to track the applied schema version. Each migration is
an idempotent-ish forward step run inside a transaction. Tables:
sessions, receiver_config, candidate_channels, detections, bursts,
config_changes, client_events, recordings.
"""

from __future__ import annotations

import structlog

from .db import Database

log = structlog.get_logger(__name__)

# Ordered list of (version, SQL). Applied when user_version < version.
_MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            stopped_at TEXT,
            start_hz INTEGER NOT NULL,
            end_hz INTEGER NOT NULL,
            backend TEXT NOT NULL,
            simulation INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS receiver_config (
            version INTEGER PRIMARY KEY,
            config_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            changed_by TEXT
        );

        CREATE TABLE IF NOT EXISTS candidate_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_hz INTEGER NOT NULL,
            bandwidth_hz INTEGER NOT NULL,
            current_power_db REAL NOT NULL,
            peak_power_db REAL NOT NULL,
            avg_power_db REAL NOT NULL,
            snr_db REAL NOT NULL,
            observation_count INTEGER NOT NULL DEFAULT 0,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            typical_burst_ms REAL,
            recurrence_interval_s REAL,
            confidence REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'active',
            fingerprint_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_channels_center ON candidate_channels(center_hz);

        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            session_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            center_hz INTEGER NOT NULL,
            bandwidth_hz INTEGER NOT NULL,
            peak_power_db REAL NOT NULL,
            avg_power_db REAL NOT NULL,
            snr_db REAL NOT NULL,
            duration_ms REAL,
            FOREIGN KEY(channel_id) REFERENCES candidate_channels(id) ON DELETE SET NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_detections_channel ON detections(channel_id);
        CREATE INDEX IF NOT EXISTS idx_detections_ts ON detections(timestamp);

        CREATE TABLE IF NOT EXISTS bursts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            session_id INTEGER,
            timestamp TEXT NOT NULL,
            duration_ms REAL,
            FOREIGN KEY(channel_id) REFERENCES candidate_channels(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_bursts_channel ON bursts(channel_id);

        CREATE TABLE IF NOT EXISTS config_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            version INTEGER NOT NULL,
            client_id TEXT,
            config_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS client_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            kind TEXT NOT NULL,
            message TEXT NOT NULL,
            client_id TEXT,
            data_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_ts ON client_events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_kind ON client_events(kind);

        CREATE TABLE IF NOT EXISTS recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            path TEXT NOT NULL,
            center_hz INTEGER NOT NULL,
            sample_rate INTEGER NOT NULL,
            gain TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            format TEXT NOT NULL,
            bytes INTEGER NOT NULL DEFAULT 0,
            sigmf_meta_json TEXT
        );
        """,
    ),
]


async def apply_migrations(db: Database) -> int:
    """Apply all pending migrations. Returns the resulting schema version."""
    conn = db.connection
    cur = await conn.execute("PRAGMA user_version;")
    row = await cur.fetchone()
    await cur.close()
    current = int(row[0]) if row else 0

    applied = current
    async with db.write_lock:
        for version, sql in _MIGRATIONS:
            if version <= current:
                continue
            await conn.executescript(sql)
            await conn.execute(f"PRAGMA user_version = {version};")
            await conn.commit()
            applied = version
            log.info("db.migration.applied", version=version)
    if applied == current:
        log.info("db.migration.up_to_date", version=current)
    return applied
