"""POST /api/scan/start, /api/scan/stop, /api/scan/focus."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..context import AppContext
from ..models import schemas
from .deps import get_context

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("/start", response_model=schemas.ScanStartResponse)
async def start(ctx: AppContext = Depends(get_context)) -> schemas.ScanStartResponse:
    session_id = await ctx.scan_manager.start_scan()
    return schemas.ScanStartResponse(ok=True, session_id=session_id)


@router.post("/stop", response_model=schemas.OkResponse)
async def stop(ctx: AppContext = Depends(get_context)) -> schemas.OkResponse:
    await ctx.scan_manager.stop_scan()
    return schemas.OkResponse(ok=True)


@router.post("/focus", response_model=schemas.OkResponse)
async def focus(
    body: schemas.FocusBody, ctx: AppContext = Depends(get_context)
) -> schemas.OkResponse:
    await ctx.scan_manager.focus(body.center_hz, body.span_hz, body.channel_id)
    return schemas.OkResponse(ok=True)
