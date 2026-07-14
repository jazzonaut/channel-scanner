"""POST /api/control/acquire and /api/control/release (single-operator lease)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..context import AppContext
from ..models import schemas
from ..utils import iso_now
from .deps import get_context

router = APIRouter(prefix="/control", tags=["control"])


@router.post("/acquire", response_model=schemas.ControlAcquireResponse)
async def acquire(
    body: schemas.ControlAcquireBody, ctx: AppContext = Depends(get_context)
) -> schemas.ControlAcquireResponse:
    ok, operator, expires = ctx.lease.acquire(body.client_id)
    if ok:
        ctx.ws.set_operator(operator)
        ctx.ws.broadcast_control(operator, expires)
        ctx.ws.broadcast_presence(operator)
        await ctx.repos.events.create(
            timestamp=iso_now(),
            kind="control_acquire",
            message=f"{body.client_id} acquired control",
            client_id=body.client_id,
        )
    return schemas.ControlAcquireResponse(ok=ok, operator_client_id=operator, lease_expires=expires)


@router.post("/release", response_model=schemas.OkResponse)
async def release(
    body: schemas.ControlReleaseBody, ctx: AppContext = Depends(get_context)
) -> schemas.OkResponse:
    released = ctx.lease.release(body.client_id)
    if released:
        ctx.ws.set_operator(None)
        ctx.ws.broadcast_control(None, None)
        ctx.ws.broadcast_presence(None)
        await ctx.repos.events.create(
            timestamp=iso_now(),
            kind="control_release",
            message=f"{body.client_id} released control",
            client_id=body.client_id,
        )
    return schemas.OkResponse(ok=released)
