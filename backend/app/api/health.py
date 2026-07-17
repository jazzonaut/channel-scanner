"""GET /api/health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from .. import __version__
from ..context import AppContext
from ..models import schemas
from .deps import get_context

router = APIRouter(tags=["health"])


@router.get("/health", response_model=schemas.HealthResponse)
async def health(
    response: Response, ctx: AppContext = Depends(get_context)
) -> schemas.HealthResponse:
    degraded = ctx.scan_manager.hardware_degraded
    if degraded:
        # Real hardware was requested but the backend fell back to simulation.
        # Return 503 so the container HEALTHCHECK (curl -f) marks the service
        # unhealthy rather than letting a silent sim fallback pass as healthy.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return schemas.HealthResponse(
        status="degraded" if degraded else "ok",
        simulation=ctx.settings.effective_simulation(),
        uptime_s=ctx.uptime_s(),
        version=__version__,
        hardware_degraded=degraded,
        detail=ctx.scan_manager.hardware_reason if degraded else None,
    )
