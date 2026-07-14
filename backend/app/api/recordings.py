"""Recording endpoints (optional IQ capture; disabled by default)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..context import AppContext
from ..models import schemas
from ..utils import iso_now
from .deps import get_context

router = APIRouter(prefix="/recordings", tags=["recordings"])


@router.post("/start", response_model=schemas.Recording)
async def start_recording(
    body: schemas.RecordingStartBody, ctx: AppContext = Depends(get_context)
) -> schemas.Recording:
    if not ctx.recorder.enabled:
        raise HTTPException(
            status_code=409,
            detail="IQ recording is disabled; set ENABLE_IQ_RECORDING=true",
        )
    backend = ctx.scan_manager.backend
    if backend is None:
        raise HTTPException(status_code=503, detail="SDR backend not initialised")

    cfg = ctx.scan_manager.config
    center = body.center_hz or (cfg.start_hz + cfg.end_hz) // 2
    duration = body.duration_ms or 1000

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: ctx.recorder.capture(
                backend,
                center_hz=center,
                duration_ms=duration,
                sample_rate=cfg.sample_rate,
                gain=cfg.gain,
                reason="manual",
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    rec = schemas.Recording(
        id=0,
        timestamp=result.timestamp,
        path=result.path,
        center_hz=result.center_hz,
        sample_rate=result.sample_rate,
        gain=result.gain,
        duration_ms=result.duration_ms,
        format=result.format,
        bytes=result.bytes,
        sigmf_meta=result.sigmf_meta,
    )
    rec_id = await ctx.repos.recordings.create(rec)
    await ctx.repos.events.create(
        timestamp=iso_now(),
        kind="recording_start",
        message=f"recording #{rec_id} at {center} Hz",
        data={"recording_id": rec_id},
    )
    return rec.model_copy(update={"id": rec_id})


@router.post("/stop", response_model=schemas.OkResponse)
async def stop_recording(ctx: AppContext = Depends(get_context)) -> schemas.OkResponse:
    # Captures are one-shot/bounded; nothing long-running to interrupt.
    await ctx.repos.events.create(
        timestamp=iso_now(), kind="recording_stop", message="recording stop requested"
    )
    return schemas.OkResponse(ok=True)


@router.get("", response_model=schemas.RecordingsResponse)
async def list_recordings(ctx: AppContext = Depends(get_context)) -> schemas.RecordingsResponse:
    recs = await ctx.repos.recordings.list()
    return schemas.RecordingsResponse(recordings=recs)


@router.delete("/{recording_id}", response_model=schemas.OkResponse)
async def delete_recording(
    recording_id: int, ctx: AppContext = Depends(get_context)
) -> schemas.OkResponse:
    rec = await ctx.repos.recordings.get(recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recording not found")
    ctx.recorder.delete_files(rec.path)
    await ctx.repos.recordings.delete(recording_id)
    return schemas.OkResponse(ok=True)
