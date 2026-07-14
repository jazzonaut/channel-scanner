"""GET /api/events."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..context import AppContext
from ..models import schemas
from .deps import get_context

router = APIRouter(tags=["events"])


@router.get("/events", response_model=schemas.EventsResponse)
async def list_events(
    limit: int = Query(200, ge=1, le=5000),
    since: str | None = Query(None),
    ctx: AppContext = Depends(get_context),
) -> schemas.EventsResponse:
    events = await ctx.repos.events.list(limit=limit, since=since)
    return schemas.EventsResponse(events=events)
