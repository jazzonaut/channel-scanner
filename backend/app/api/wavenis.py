"""Read-only Wavenis wideband evidence status."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..context import AppContext
from .deps import get_context

router = APIRouter(tags=["wavenis"])


@router.get("/wavenis")
async def get_wavenis_status(ctx: AppContext = Depends(get_context)) -> dict[str, object]:
    return ctx.scan_manager.wavenis_status()


@router.get("/wavenis/candidates")
async def get_wavenis_candidates(
    limit: int = 500, ctx: AppContext = Depends(get_context)
) -> dict[str, object]:
    """Durable list of auto-flagged candidates (survives restart/reboot)."""
    return ctx.scan_manager.candidates(limit=max(1, min(limit, 5000)))
