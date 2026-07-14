"""GET /api/channels, /api/channels/{id}, /api/channels/{id}/observations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..context import AppContext
from ..models import schemas
from .deps import get_context

router = APIRouter(prefix="/channels", tags=["channels"])


@router.get("", response_model=schemas.ChannelsResponse)
async def list_channels(ctx: AppContext = Depends(get_context)) -> schemas.ChannelsResponse:
    channels = await ctx.repos.channels.list()
    return schemas.ChannelsResponse(channels=channels)


@router.get("/{channel_id}", response_model=schemas.CandidateChannel)
async def get_channel(
    channel_id: int, ctx: AppContext = Depends(get_context)
) -> schemas.CandidateChannel:
    ch = await ctx.repos.channels.get(channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="channel not found")
    return ch


@router.get("/{channel_id}/observations", response_model=schemas.ObservationsResponse)
async def channel_observations(
    channel_id: int,
    limit: int = Query(200, ge=1, le=5000),
    ctx: AppContext = Depends(get_context),
) -> schemas.ObservationsResponse:
    obs = await ctx.repos.detections.list_for_channel(channel_id, limit=limit)
    return schemas.ObservationsResponse(observations=obs)
