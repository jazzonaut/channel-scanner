"""Async SQLite database wrapper.

A single shared aiosqlite connection in WAL mode, guarded by an asyncio lock for
writes. All timestamps are stored as ISO-8601 UTC text. The DB path comes from
settings; parent directories are created on connect.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import structlog

log = structlog.get_logger(__name__)


class Database:
    """Owns the aiosqlite connection lifecycle and a write lock."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected; call connect() first.")
        return self._conn

    @property
    def write_lock(self) -> asyncio.Lock:
        return self._write_lock

    async def connect(self) -> None:
        if self._conn is not None:
            return
        if str(self._path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.execute("PRAGMA busy_timeout=5000;")
        await self._conn.commit()
        log.info("db.connected", path=str(self._path))

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            log.info("db.closed", path=str(self._path))

    async def db_size_bytes(self) -> int:
        try:
            if str(self._path) == ":memory:":
                cur = await self.connection.execute(
                    "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size();"
                )
                row = await cur.fetchone()
                await cur.close()
                return int(row[0]) if row and row[0] is not None else 0
            return self._path.stat().st_size if self._path.exists() else 0
        except OSError:
            return 0

    async def __aenter__(self) -> Database:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
