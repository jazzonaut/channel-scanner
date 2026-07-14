"""Single-operator control lease.

Exactly one client may hold the control lease at a time; only the lease holder
may mutate configuration or start/stop scans. View-only clients still receive
all live updates. Leases expire after a TTL unless renewed, so a disconnected
operator does not lock everyone out.
"""

from __future__ import annotations

import threading
from datetime import timedelta

from ..utils import iso, utcnow


class ControlLease:
    """Thread-safe single-operator lease with expiry."""

    def __init__(self, ttl_seconds: float = 120.0) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._operator: str | None = None
        self._expires = utcnow()
        self._lock = threading.Lock()

    def _expired(self) -> bool:
        return self._operator is not None and utcnow() >= self._expires

    @property
    def operator(self) -> str | None:
        with self._lock:
            if self._expired():
                self._operator = None
            return self._operator

    @property
    def expires_iso(self) -> str | None:
        with self._lock:
            if self._operator is None or self._expired():
                return None
            return iso(self._expires)

    def acquire(self, client_id: str) -> tuple[bool, str | None, str | None]:
        """Acquire or renew the lease.

        Returns (ok, operator_client_id, lease_expires_iso). Succeeds if the
        lease is free/expired or already held by this client (renew).
        """
        with self._lock:
            if self._expired():
                self._operator = None
            if self._operator is None or self._operator == client_id:
                self._operator = client_id
                self._expires = utcnow() + self._ttl
                return True, self._operator, iso(self._expires)
            return False, self._operator, iso(self._expires)

    def release(self, client_id: str) -> bool:
        """Release the lease if held by this client."""
        with self._lock:
            if self._operator == client_id:
                self._operator = None
                return True
            return False

    def renew(self, client_id: str) -> bool:
        """Extend the lease TTL if held by this client."""
        with self._lock:
            if self._operator == client_id and not self._expired():
                self._expires = utcnow() + self._ttl
                return True
            return False

    def is_operator(self, client_id: str | None) -> bool:
        if client_id is None:
            return False
        return self.operator == client_id

    def force_release(self) -> None:
        with self._lock:
            self._operator = None
