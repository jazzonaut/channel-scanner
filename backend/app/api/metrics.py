"""GET /api/metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..context import AppContext
from ..models import schemas
from .deps import get_context

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=schemas.MetricsResponse)
async def metrics(ctx: AppContext = Depends(get_context)) -> schemas.MetricsResponse:
    m = await ctx.scan_manager.metrics_dict()
    return schemas.MetricsResponse(**m)
