"""Durable, append-only log of auto-flagged Wavenis candidates.

Candidates must survive the in-memory rolling window, scan restarts, config
changes, and process reboots -- the whole point is to leave a scan running for a
day and still find whatever it caught. Each flagged burst is appended as one
JSON line under the logs directory. The file is never rewritten in place, is not
subject to IQ-recording retention, and is only removed on an explicit
"clear all data" action.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_FILENAME = "wavenis_candidates.jsonl"


class CandidateLog:
    """Append-only JSONL store for flagged Wavenis candidates."""

    def __init__(self, logs_dir: Path) -> None:
        self._path = Path(logs_dir) / _FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: dict) -> None:
        """Append one candidate record. Best-effort; never raises into the loop."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError as exc:  # pragma: no cover - disk full / permissions
            log.warning("candidate_log.append_failed", error=str(exc), path=str(self._path))

    def read_all(self, limit: int | None = None) -> list[dict]:
        """Return persisted candidates, newest first. Skips any corrupt line."""
        if not self._path.exists():
            return []
        records: list[dict] = []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:  # pragma: no cover - defensive
            log.warning("candidate_log.read_failed", error=str(exc), path=str(self._path))
            return []
        records.reverse()
        return records[:limit] if limit is not None else records

    def count(self) -> int:
        """Total persisted candidates on disk."""
        if not self._path.exists():
            return 0
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:  # pragma: no cover - defensive
            return 0

    def clear(self) -> None:
        """Remove the durable log (explicit user action only)."""
        try:
            self._path.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - defensive
            log.warning("candidate_log.clear_failed", error=str(exc), path=str(self._path))
