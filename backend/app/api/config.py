"""GET/PUT /api/config.

PUT enforces optimistic concurrency (version conflict -> 409) and the control
lease (only the operator may change config). A config_change event is logged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..context import AppContext
from ..models import schemas
from .deps import get_context

router = APIRouter(tags=["config"])


@router.get("/config", response_model=schemas.ConfigResponse)
async def get_config(ctx: AppContext = Depends(get_context)) -> schemas.ConfigResponse:
    sm = ctx.scan_manager
    return schemas.ConfigResponse(**sm.config_dict(), version=sm.version)


@router.put("/config", response_model=schemas.ConfigResponse)
async def put_config(
    body: schemas.ConfigPutBody, ctx: AppContext = Depends(get_context)
) -> schemas.ConfigResponse:
    sm = ctx.scan_manager

    # Control lease: only the operator may mutate config.
    if not ctx.lease.is_operator(body.client_id):
        raise HTTPException(
            status_code=403,
            detail="control lease required; acquire it via POST /api/control/acquire",
        )

    # Optimistic concurrency.
    if body.version != sm.version:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "version_conflict",
                "expected": sm.version,
                "provided": body.version,
            },
        )

    update = schemas.ScanConfigUpdate(
        **body.model_dump(exclude={"version", "client_id"}, exclude_unset=True)
    )
    try:
        await sm.update_config(update, client_id=body.client_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ctx.lease.renew(body.client_id)
    return schemas.ConfigResponse(**sm.config_dict(), version=sm.version)
