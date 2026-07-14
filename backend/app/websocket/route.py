"""The /ws/live WebSocket endpoint.

Protocol (see CONTRACT.md): client sends `identify` first; server replies with
`hello` (client_id, version, config, operator_client_id), then streams
spectrum/channels/events/presence/control/status/config messages. Server also
answers `ping` with `pong`. Only reduced spectrum frames are sent -- never IQ.
"""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..context import AppContext

log = structlog.get_logger(__name__)

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    ctx: AppContext = websocket.app.state.ctx
    await websocket.accept()

    # Wait for the initial identify message (with a timeout).
    client_id: str | None = None
    display_name: str | None = None
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        if isinstance(first, dict) and first.get("type") == "identify":
            client_id = first.get("client_id")
            display_name = first.get("display_name")
    except (TimeoutError, WebSocketDisconnect, ValueError):
        # Proceed anonymously; register will mint an id.
        pass

    conn = await ctx.ws.register(websocket, client_id=client_id, display_name=display_name)
    send_task = asyncio.create_task(conn.run_send_loop(), name=f"ws-send-{conn.client_id}")

    # Send hello and initial presence/control snapshot.
    operator = ctx.lease.operator
    conn.enqueue(
        {
            "type": "hello",
            "client_id": conn.client_id,
            "version": ctx.scan_manager.version,
            "config": ctx.scan_manager.config_dict(),
            "operator_client_id": operator,
        }
    )
    ctx.ws.broadcast_presence(operator)
    # Give this client an immediate status snapshot.
    conn.enqueue(
        {
            "type": "status",
            "device": ctx.scan_manager.device_info(),
            "metrics": await ctx.scan_manager.metrics_dict(),
            "scanning": ctx.scan_manager.scanning,
        }
    )

    try:
        while True:
            msg = await websocket.receive_json()
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("type")
            if mtype == "ping":
                conn.enqueue({"type": "pong"})
            elif mtype == "identify":
                # Allow updating display name mid-session.
                name = msg.get("display_name")
                if name:
                    conn.display_name = name
                    ctx.ws.broadcast_presence(ctx.lease.operator)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.info("ws.recv_error", client_id=conn.client_id, error=str(exc))
    finally:
        conn.close()
        send_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await send_task
        await ctx.ws.unregister(conn.client_id)
        # If the operator disconnected, release the lease.
        if ctx.lease.operator == conn.client_id:
            ctx.lease.release(conn.client_id)
            ctx.ws.set_operator(None)
            ctx.ws.broadcast_control(None, None)
        ctx.ws.broadcast_presence(ctx.lease.operator)
