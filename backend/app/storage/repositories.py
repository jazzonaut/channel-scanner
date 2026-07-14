"""Async repositories (CRUD) over the SQLite tables.

Each repository maps rows to Pydantic schemas from app.models.schemas. Writes go
through the Database write lock. Times are ISO-8601 UTC text.
"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from ..models import schemas
from .db import Database


def _loads(value: str | None) -> Any | None:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, *, started_at: str, start_hz: int, end_hz: int, backend: str, simulation: bool
    ) -> int:
        async with self._db.write_lock:
            cur = await self._db.connection.execute(
                "INSERT INTO sessions(started_at, start_hz, end_hz, backend, simulation) "
                "VALUES (?,?,?,?,?)",
                (started_at, start_hz, end_hz, backend, int(simulation)),
            )
            await self._db.connection.commit()
            return int(cur.lastrowid)

    async def stop(self, session_id: int, stopped_at: str) -> None:
        async with self._db.write_lock:
            await self._db.connection.execute(
                "UPDATE sessions SET stopped_at=? WHERE id=?", (stopped_at, session_id)
            )
            await self._db.connection.commit()

    async def list(self, limit: int = 100) -> list[schemas.Session]:
        cur = await self._db.connection.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        await cur.close()
        return [self._to_model(r) for r in rows]

    async def get(self, session_id: int) -> schemas.Session | None:
        cur = await self._db.connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
        row = await cur.fetchone()
        await cur.close()
        return self._to_model(row) if row else None

    @staticmethod
    def _to_model(r: aiosqlite.Row) -> schemas.Session:
        return schemas.Session(
            id=r["id"],
            started_at=r["started_at"],
            stopped_at=r["stopped_at"],
            start_hz=r["start_hz"],
            end_hz=r["end_hz"],
            backend=r["backend"],
            simulation=bool(r["simulation"]),
        )


class ChannelRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, ch: schemas.CandidateChannel) -> int:
        fp = json.dumps(ch.fingerprint.model_dump()) if ch.fingerprint else None
        async with self._db.write_lock:
            if ch.id and await self._exists(ch.id):
                await self._db.connection.execute(
                    """
                    UPDATE candidate_channels SET
                      center_hz=?, bandwidth_hz=?, current_power_db=?, peak_power_db=?,
                      avg_power_db=?, snr_db=?, observation_count=?, first_seen=?,
                      last_seen=?, typical_burst_ms=?, recurrence_interval_s=?,
                      confidence=?, status=?, fingerprint_json=?
                    WHERE id=?
                    """,
                    (
                        ch.center_hz,
                        ch.bandwidth_hz,
                        ch.current_power_db,
                        ch.peak_power_db,
                        ch.avg_power_db,
                        ch.snr_db,
                        ch.observation_count,
                        ch.first_seen,
                        ch.last_seen,
                        ch.typical_burst_ms,
                        ch.recurrence_interval_s,
                        ch.confidence,
                        ch.status,
                        fp,
                        ch.id,
                    ),
                )
                await self._db.connection.commit()
                return ch.id
            cur = await self._db.connection.execute(
                """
                INSERT INTO candidate_channels(
                  id, center_hz, bandwidth_hz, current_power_db, peak_power_db, avg_power_db,
                  snr_db, observation_count, first_seen, last_seen, typical_burst_ms,
                  recurrence_interval_s, confidence, status, fingerprint_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ch.id or None,
                    ch.center_hz,
                    ch.bandwidth_hz,
                    ch.current_power_db,
                    ch.peak_power_db,
                    ch.avg_power_db,
                    ch.snr_db,
                    ch.observation_count,
                    ch.first_seen,
                    ch.last_seen,
                    ch.typical_burst_ms,
                    ch.recurrence_interval_s,
                    ch.confidence,
                    ch.status,
                    fp,
                ),
            )
            await self._db.connection.commit()
            return int(cur.lastrowid)

    async def _exists(self, channel_id: int) -> bool:
        cur = await self._db.connection.execute(
            "SELECT 1 FROM candidate_channels WHERE id=?", (channel_id,)
        )
        row = await cur.fetchone()
        await cur.close()
        return row is not None

    async def list(self, limit: int = 500) -> list[schemas.CandidateChannel]:
        cur = await self._db.connection.execute(
            "SELECT * FROM candidate_channels ORDER BY center_hz ASC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        await cur.close()
        return [self._to_model(r) for r in rows]

    async def get(self, channel_id: int) -> schemas.CandidateChannel | None:
        cur = await self._db.connection.execute(
            "SELECT * FROM candidate_channels WHERE id=?", (channel_id,)
        )
        row = await cur.fetchone()
        await cur.close()
        return self._to_model(row) if row else None

    @staticmethod
    def _to_model(r: aiosqlite.Row) -> schemas.CandidateChannel:
        fp_raw = _loads(r["fingerprint_json"])
        return schemas.CandidateChannel(
            id=r["id"],
            center_hz=r["center_hz"],
            bandwidth_hz=r["bandwidth_hz"],
            current_power_db=r["current_power_db"],
            peak_power_db=r["peak_power_db"],
            avg_power_db=r["avg_power_db"],
            snr_db=r["snr_db"],
            observation_count=r["observation_count"],
            first_seen=r["first_seen"],
            last_seen=r["last_seen"],
            typical_burst_ms=r["typical_burst_ms"],
            recurrence_interval_s=r["recurrence_interval_s"],
            confidence=r["confidence"],
            status=r["status"],
            fingerprint=schemas.Fingerprint(**fp_raw) if fp_raw else None,
        )


class DetectionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, d: schemas.Detection) -> int:
        async with self._db.write_lock:
            cur = await self._db.connection.execute(
                """
                INSERT INTO detections(
                  channel_id, session_id, timestamp, center_hz, bandwidth_hz,
                  peak_power_db, avg_power_db, snr_db, duration_ms)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    d.channel_id,
                    d.session_id,
                    d.timestamp,
                    d.center_hz,
                    d.bandwidth_hz,
                    d.peak_power_db,
                    d.avg_power_db,
                    d.snr_db,
                    d.duration_ms,
                ),
            )
            await self._db.connection.commit()
            return int(cur.lastrowid)

    async def list_for_channel(self, channel_id: int, limit: int = 200) -> list[schemas.Detection]:
        cur = await self._db.connection.execute(
            "SELECT * FROM detections WHERE channel_id=? ORDER BY id DESC LIMIT ?",
            (channel_id, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        return [self._to_model(r) for r in rows]

    async def list_all(self, limit: int = 1000) -> list[schemas.Detection]:
        cur = await self._db.connection.execute(
            "SELECT * FROM detections ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        await cur.close()
        return [self._to_model(r) for r in rows]

    @staticmethod
    def _to_model(r: aiosqlite.Row) -> schemas.Detection:
        return schemas.Detection(
            id=r["id"],
            channel_id=r["channel_id"],
            session_id=r["session_id"],
            timestamp=r["timestamp"],
            center_hz=r["center_hz"],
            bandwidth_hz=r["bandwidth_hz"],
            peak_power_db=r["peak_power_db"],
            avg_power_db=r["avg_power_db"],
            snr_db=r["snr_db"],
            duration_ms=r["duration_ms"],
        )


class BurstRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        channel_id: int,
        timestamp: str,
        duration_ms: float | None,
        session_id: int | None = None,
    ) -> int:
        async with self._db.write_lock:
            cur = await self._db.connection.execute(
                "INSERT INTO bursts(channel_id, session_id, timestamp, duration_ms) "
                "VALUES (?,?,?,?)",
                (channel_id, session_id, timestamp, duration_ms),
            )
            await self._db.connection.commit()
            return int(cur.lastrowid)

    async def list_for_channel(self, channel_id: int, limit: int = 500) -> list[dict]:
        cur = await self._db.connection.execute(
            "SELECT * FROM bursts WHERE channel_id=? ORDER BY id DESC LIMIT ?",
            (channel_id, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]


class EventRepository:
    """Backed by the client_events table; serves /api/events."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        timestamp: str,
        kind: str,
        message: str,
        client_id: str | None = None,
        data: dict | None = None,
    ) -> int:
        data_json = json.dumps(data) if data is not None else None
        async with self._db.write_lock:
            cur = await self._db.connection.execute(
                "INSERT INTO client_events(timestamp, kind, message, client_id, data_json) "
                "VALUES (?,?,?,?,?)",
                (timestamp, kind, message, client_id, data_json),
            )
            await self._db.connection.commit()
            return int(cur.lastrowid)

    async def list(self, limit: int = 200, since: str | None = None) -> list[schemas.Event]:
        if since:
            cur = await self._db.connection.execute(
                "SELECT * FROM client_events WHERE timestamp > ? ORDER BY id DESC LIMIT ?",
                (since, limit),
            )
        else:
            cur = await self._db.connection.execute(
                "SELECT * FROM client_events ORDER BY id DESC LIMIT ?", (limit,)
            )
        rows = await cur.fetchall()
        await cur.close()
        return [self._to_model(r) for r in rows]

    @staticmethod
    def _to_model(r: aiosqlite.Row) -> schemas.Event:
        return schemas.Event(
            id=r["id"],
            timestamp=r["timestamp"],
            kind=r["kind"],
            message=r["message"],
            client_id=r["client_id"],
            data=_loads(r["data_json"]),
        )


class ConfigChangeRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self, *, timestamp: str, version: int, client_id: str | None, config_json: str
    ) -> int:
        async with self._db.write_lock:
            cur = await self._db.connection.execute(
                "INSERT INTO config_changes(timestamp, version, client_id, config_json) "
                "VALUES (?,?,?,?)",
                (timestamp, version, client_id, config_json),
            )
            await self._db.connection.commit()
            return int(cur.lastrowid)

    async def latest_version(self) -> int:
        cur = await self._db.connection.execute("SELECT MAX(version) AS v FROM config_changes")
        row = await cur.fetchone()
        await cur.close()
        return int(row["v"]) if row and row["v"] is not None else 0


class ReceiverConfigRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(
        self, *, version: int, config_json: str, updated_at: str, changed_by: str | None
    ) -> None:
        async with self._db.write_lock:
            await self._db.connection.execute(
                "INSERT OR REPLACE INTO receiver_config(version, config_json, updated_at, "
                "changed_by) VALUES (?,?,?,?)",
                (version, config_json, updated_at, changed_by),
            )
            await self._db.connection.commit()

    async def latest(self) -> tuple[int, dict] | None:
        cur = await self._db.connection.execute(
            "SELECT version, config_json FROM receiver_config ORDER BY version DESC LIMIT 1"
        )
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        return int(row["version"]), (_loads(row["config_json"]) or {})


class RecordingRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, rec: schemas.Recording) -> int:
        meta = json.dumps(rec.sigmf_meta) if rec.sigmf_meta is not None else None
        async with self._db.write_lock:
            cur = await self._db.connection.execute(
                """
                INSERT INTO recordings(timestamp, path, center_hz, sample_rate, gain,
                  duration_ms, format, bytes, sigmf_meta_json)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    rec.timestamp,
                    rec.path,
                    rec.center_hz,
                    rec.sample_rate,
                    rec.gain,
                    rec.duration_ms,
                    rec.format,
                    rec.bytes,
                    meta,
                ),
            )
            await self._db.connection.commit()
            return int(cur.lastrowid)

    async def list(self, limit: int = 200) -> list[schemas.Recording]:
        cur = await self._db.connection.execute(
            "SELECT * FROM recordings ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        await cur.close()
        return [self._to_model(r) for r in rows]

    async def get(self, rec_id: int) -> schemas.Recording | None:
        cur = await self._db.connection.execute("SELECT * FROM recordings WHERE id=?", (rec_id,))
        row = await cur.fetchone()
        await cur.close()
        return self._to_model(row) if row else None

    async def delete(self, rec_id: int) -> bool:
        async with self._db.write_lock:
            cur = await self._db.connection.execute("DELETE FROM recordings WHERE id=?", (rec_id,))
            await self._db.connection.commit()
            return cur.rowcount > 0

    async def total_bytes(self) -> int:
        cur = await self._db.connection.execute(
            "SELECT COALESCE(SUM(bytes),0) AS total FROM recordings"
        )
        row = await cur.fetchone()
        await cur.close()
        return int(row["total"]) if row else 0

    @staticmethod
    def _to_model(r: aiosqlite.Row) -> schemas.Recording:
        return schemas.Recording(
            id=r["id"],
            timestamp=r["timestamp"],
            path=r["path"],
            center_hz=r["center_hz"],
            sample_rate=r["sample_rate"],
            gain=r["gain"],
            duration_ms=r["duration_ms"],
            format=r["format"],
            bytes=r["bytes"],
            sigmf_meta=_loads(r["sigmf_meta_json"]),
        )


class Repositories:
    """Aggregate handle to all repositories."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.sessions = SessionRepository(db)
        self.channels = ChannelRepository(db)
        self.detections = DetectionRepository(db)
        self.bursts = BurstRepository(db)
        self.events = EventRepository(db)
        self.config_changes = ConfigChangeRepository(db)
        self.receiver_config = ReceiverConfigRepository(db)
        self.recordings = RecordingRepository(db)
