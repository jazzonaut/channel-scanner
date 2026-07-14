"""Aggregate API router mounted under /api."""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    channels,
    clients,
    config,
    control,
    device,
    events,
    export,
    health,
    metrics,
    recordings,
    scan,
    sessions,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(metrics.router)
api_router.include_router(device.router)
api_router.include_router(config.router)
api_router.include_router(scan.router)
api_router.include_router(channels.router)
api_router.include_router(events.router)
api_router.include_router(sessions.router)
api_router.include_router(export.router)
api_router.include_router(recordings.router)
api_router.include_router(clients.router)
api_router.include_router(control.router)

__all__ = ["api_router"]
