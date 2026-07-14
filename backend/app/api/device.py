"""GET /api/device."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..context import AppContext
from ..models import schemas
from .deps import get_context

router = APIRouter(tags=["device"])


@router.get("/device", response_model=schemas.DeviceInfo)
async def device(ctx: AppContext = Depends(get_context)) -> schemas.DeviceInfo:
    return schemas.DeviceInfo(**ctx.scan_manager.device_info())
