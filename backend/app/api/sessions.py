"""GET /api/sessions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..context import AppContext
from ..models import schemas
from .deps import get_context

router = APIRouter(tags=["sessions"])


@router.get("/sessions", response_model=schemas.SessionsResponse)
async def list_sessions(
    limit: int = Query(100, ge=1, le=1000),
    ctx: AppContext = Depends(get_context),
) -> schemas.SessionsResponse:
    sessions = await ctx.repos.sessions.list(limit=limit)
    return schemas.SessionsResponse(sessions=sessions)
