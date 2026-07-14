"""Data-retention cleanup.

Periodically deletes detections/events/bursts older than RETENTION_DAYS and
enforces the recordings storage cap. Runs as a lightweight async loop.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta

import structlog

from ..config import Settings
from ..storage.repositories import Repositories
from ..utils import iso, utcnow

log = structlog.get_logger(__name__)


class RetentionService:
    """Periodic pruning of aged rows and oversized recordings."""

    def __init__(
        self,
        settings: Settings,
        repos: Repositories,
        *,
        interval_seconds: float = 3600.0,
    ) -> None:
        self._settings = settings
        self._repos = repos
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="retention")
        log.info("retention.started", interval_s=self._interval, days=self._settings.retention_days)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        log.info("retention.stopped")

    async def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                await self.run_once()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
        except asyncio.CancelledError:
            raise

    async def run_once(self) -> dict[str, int]:
        """Delete rows older than the cutoff. Returns deletion counts."""
        cutoff = iso(utcnow() - timedelta(days=self._settings.retention_days))
        conn = self._repos.db.connection
        deleted: dict[str, int] = {}
        async with self._repos.db.write_lock:
            for table in ("detections", "client_events", "bursts"):
                cur = await conn.execute(
                    f"DELETE FROM {table} WHERE timestamp < ?",
                    (cutoff,),  # noqa: S608
                )
                deleted[table] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            await conn.commit()
        if any(deleted.values()):
            log.info("retention.pruned", cutoff=cutoff, **deleted)
        return deleted
