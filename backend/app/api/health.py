"""GET /api/health."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import __version__
from ..context import AppContext
from ..models import schemas
from .deps import get_context

router = APIRouter(tags=["health"])


@router.get("/health", response_model=schemas.HealthResponse)
async def health(ctx: AppContext = Depends(get_context)) -> schemas.HealthResponse:
    return schemas.HealthResponse(
        status="ok",
        simulation=ctx.settings.effective_simulation(),
        uptime_s=ctx.uptime_s(),
        version=__version__,
    )
