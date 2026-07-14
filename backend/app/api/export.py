"""GET /api/export.csv and /api/export.json (streamed downloads)."""

from __future__ import annotations

import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ..context import AppContext
from .deps import get_context

router = APIRouter(tags=["export"])

Kind = Literal["channels", "detections", "events"]


async def _collect(ctx: AppContext, kind: Kind) -> list[dict]:
    if kind == "channels":
        rows = await ctx.repos.channels.list(limit=10_000)
    elif kind == "detections":
        rows = await ctx.repos.detections.list_all(limit=50_000)
    else:
        rows = await ctx.repos.events.list(limit=50_000)
    return [r.model_dump(mode="json") for r in rows]


@router.get("/export.csv")
async def export_csv(
    kind: Kind = Query("channels"), ctx: AppContext = Depends(get_context)
) -> StreamingResponse:
    data = await _collect(ctx, kind)
    buf = io.StringIO()
    if data:
        # Flatten nested objects (fingerprint/data) to JSON strings for CSV.
        fieldnames = list(data[0].keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in data:
            flat = {
                k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()
            }
            writer.writerow(flat)
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{kind}.csv"'}
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)


@router.get("/export.json")
async def export_json(
    kind: Kind = Query("channels"), ctx: AppContext = Depends(get_context)
) -> StreamingResponse:
    data = await _collect(ctx, kind)
    payload = json.dumps({"kind": kind, kind: data}, indent=2)
    headers = {"Content-Disposition": f'attachment; filename="{kind}.json"'}
    return StreamingResponse(iter([payload]), media_type="application/json", headers=headers)
