"""FastAPI dependency helpers to access the AppContext."""

from __future__ import annotations

from fastapi import Request

from ..context import AppContext


def get_context(request: Request) -> AppContext:
    ctx: AppContext | None = getattr(request.app.state, "ctx", None)
    if ctx is None:  # pragma: no cover - defensive
        raise RuntimeError("Application context is not initialised")
    return ctx
