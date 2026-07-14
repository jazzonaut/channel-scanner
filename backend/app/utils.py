"""Small shared helpers (time formatting)."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    """Current UTC time as ISO-8601 with millisecond precision and trailing Z."""
    return iso(utcnow())


def iso(dt: datetime) -> str:
    """Format a datetime as ISO-8601 UTC with millisecond precision + Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
