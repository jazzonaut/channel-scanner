"""Connection hub for /ws/live.

Tracks connected clients (anonymous generated IDs + optional display names),
maintains a per-client bounded send buffer that keeps only the latest spectrum
frame (dropping stale ones) while delivering channel/event/presence/control
messages reliably, and provides typed broadcast helpers.

Only REDUCED spectrum frames are ever sent -- never raw IQ.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections import deque
from datetime import UTC, datetime
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Message types considered "droppable if stale" (only latest kept).
_STALE_DROPPABLE = {"spectrum"}


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{datetime.now(UTC).microsecond // 1000:03d}Z"
    )


class ClientConnection:
    """A single websocket client with a bounded, spectrum-coalescing buffer."""

    def __init__(
        self,
        websocket: Any,
        client_id: str,
        display_name: str,
        *,
        max_buffer: int = 64,
    ) -> None:
        self.websocket = websocket
        self.client_id = client_id
        self.display_name = display_name
        self.connected_at = _utcnow_iso()
        self.is_operator = False
        self._buf: deque[dict[str, Any]] = deque()
        self._max = max_buffer
        self._event = asyncio.Event()
        self._closed = False
        self.dropped_frames = 0

    @property
    def queue_depth(self) -> int:
        return len(self._buf)

    def enqueue(self, message: dict[str, Any]) -> None:
        """Buffer a message. Coalesces spectrum frames; bounds total size."""
        if self._closed:
            return
        mtype = message.get("type")
        if mtype in _STALE_DROPPABLE:
            # Keep only the newest spectrum frame.
            removed = False
            for i, m in enumerate(self._buf):
                if m.get("type") == mtype:
                    del self._buf[i]
                    removed = True
                    break
            if removed:
                self.dropped_frames += 1
            elif len(self._buf) >= self._max:
                # No stale spectrum to replace and buffer full -> drop this frame.
                self.dropped_frames += 1
                return
            self._buf.append(message)
        else:
            # Reliable message. If over cap, evict oldest spectrum, else oldest.
            if len(self._buf) >= self._max:
                idx = next(
                    (i for i, m in enumerate(self._buf) if m.get("type") in _STALE_DROPPABLE),
                    0,
                )
                del self._buf[idx]
                self.dropped_frames += 1
            self._buf.append(message)
        self._event.set()

    async def run_send_loop(self) -> None:
        """Drain the buffer to the socket until closed."""
        try:
            while not self._closed:
                if not self._buf:
                    self._event.clear()
                    await self._event.wait()
                    continue
                message = self._buf.popleft()
                await self.websocket.send_json(message)
        except (asyncio.CancelledError, RuntimeError):
            raise
        except Exception as exc:  # noqa: BLE001 - connection errors end the loop
            log.info("ws.send_loop.closed", client_id=self.client_id, error=str(exc))
        finally:
            self._closed = True

    def close(self) -> None:
        self._closed = True
        self._event.set()


class ConnectionManager:
    """Hub tracking all clients and broadcasting typed messages."""

    def __init__(self, *, max_buffer: int = 64) -> None:
        self._clients: dict[str, ClientConnection] = {}
        self._max_buffer = max_buffer
        self._lock = asyncio.Lock()

    # --- lifecycle ---
    async def register(
        self, websocket: Any, *, client_id: str | None, display_name: str | None
    ) -> ClientConnection:
        cid = client_id or f"anon-{secrets.token_hex(4)}"
        name = display_name or f"guest-{cid[-4:]}"
        conn = ClientConnection(websocket, cid, name, max_buffer=self._max_buffer)
        async with self._lock:
            # Replace any prior connection with the same id.
            old = self._clients.get(cid)
            if old is not None:
                old.close()
            self._clients[cid] = conn
        log.info("ws.client.connected", client_id=cid, display_name=name)
        return conn

    async def unregister(self, client_id: str) -> None:
        async with self._lock:
            conn = self._clients.pop(client_id, None)
        if conn is not None:
            conn.close()
        log.info("ws.client.disconnected", client_id=client_id)

    # --- introspection ---
    @property
    def client_count(self) -> int:
        return len(self._clients)

    def total_queue_depth(self) -> int:
        return sum(c.queue_depth for c in self._clients.values())

    def total_dropped_frames(self) -> int:
        return sum(c.dropped_frames for c in self._clients.values())

    def clients_info(self, operator_client_id: str | None) -> list[dict[str, Any]]:
        return [
            {
                "client_id": c.client_id,
                "display_name": c.display_name,
                "connected_at": c.connected_at,
                "is_operator": c.client_id == operator_client_id,
            }
            for c in self._clients.values()
        ]

    def set_operator(self, operator_client_id: str | None) -> None:
        for c in self._clients.values():
            c.is_operator = c.client_id == operator_client_id

    # --- broadcasting ---
    def _broadcast(self, message: dict[str, Any]) -> None:
        for c in list(self._clients.values()):
            c.enqueue(message)

    def send_to(self, client_id: str, message: dict[str, Any]) -> None:
        conn = self._clients.get(client_id)
        if conn is not None:
            conn.enqueue(message)

    def broadcast_spectrum(self, payload: dict[str, Any]) -> None:
        self._broadcast({"type": "spectrum", **payload})

    def broadcast_channels(self, channels: list[dict[str, Any]]) -> None:
        self._broadcast({"type": "channels", "channels": channels})

    def broadcast_channel_update(self, channel: dict[str, Any]) -> None:
        self._broadcast({"type": "channel_update", "channel": channel})

    def broadcast_event(self, event: dict[str, Any]) -> None:
        self._broadcast({"type": "event", "event": event})

    def broadcast_status(
        self, device: dict[str, Any], metrics: dict[str, Any], scanning: bool
    ) -> None:
        self._broadcast(
            {"type": "status", "device": device, "metrics": metrics, "scanning": scanning}
        )

    def broadcast_config(
        self, config: dict[str, Any], version: int, changed_by: str | None
    ) -> None:
        self._broadcast(
            {"type": "config", "config": config, "version": version, "changed_by": changed_by}
        )

    def broadcast_presence(self, operator_client_id: str | None) -> None:
        clients = self.clients_info(operator_client_id)
        self._broadcast(
            {
                "type": "presence",
                "clients": clients,
                "count": len(clients),
                "operator_client_id": operator_client_id,
            }
        )

    def broadcast_control(self, operator_client_id: str | None, lease_expires: str | None) -> None:
        self._broadcast(
            {
                "type": "control",
                "operator_client_id": operator_client_id,
                "lease_expires": lease_expires,
            }
        )

    async def close_all(self) -> None:
        async with self._lock:
            for c in self._clients.values():
                c.close()
                with contextlib.suppress(Exception):
                    await c.websocket.close()
            self._clients.clear()
