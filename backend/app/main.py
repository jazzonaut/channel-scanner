"""FastAPI application factory.

Wires together configuration, structured logging, the SQLite store, the scan
manager, websocket hub and all API routers. Serves the built frontend from the
static dir at "/" with SPA fallback to index.html. RECEIVE-ONLY throughout.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from . import __version__
from .api import api_router
from .config import Settings, get_settings
from .context import AppContext, build_context
from .logging_setup import configure_logging
from .storage.migrations import apply_migrations
from .websocket.route import router as ws_router

log = structlog.get_logger(__name__)


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html for unknown (SPA) routes."""

    async def get_response(self, path: str, scope) -> Response:  # noqa: ANN001
        try:
            return await super().get_response(path, scope)
        except Exception:  # noqa: BLE001 - includes 404 -> serve SPA shell
            index = Path(self.directory) / "index.html"
            if index.is_file():
                return FileResponse(str(index))
            return Response("Not found", status_code=404)


def _build_lifespan(settings: Settings):
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(level=settings.log_level, log_dir=settings.log_dir)
        ctx: AppContext = build_context(settings)
        app.state.ctx = ctx

        await ctx.db.connect()
        await apply_migrations(ctx.db)
        await ctx.scan_manager.startup()
        await ctx.retention.start()
        log.info("app.startup.complete", version=__version__)
        try:
            yield
        finally:
            with contextlib.suppress(Exception):
                await ctx.retention.stop()
            with contextlib.suppress(Exception):
                await ctx.decoder.stop()
            with contextlib.suppress(Exception):
                await ctx.scan_manager.shutdown()
            with contextlib.suppress(Exception):
                await ctx.ws.close_all()
            with contextlib.suppress(Exception):
                await ctx.db.close()
            log.info("app.shutdown.complete")

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory."""
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, log_dir=settings.log_dir)

    app = FastAPI(
        title="rtl-sdr-channel-detector",
        version=__version__,
        description="Receive-only RTL-SDR passive spectrum monitor (backend).",
        docs_url="/api/docs",
        openapi_url="/openapi.json",
        lifespan=_build_lifespan(settings),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API + WebSocket routes are registered BEFORE the catch-all static mount.
    app.include_router(api_router)
    app.include_router(ws_router)

    static_dir = Path(settings.static_dir)
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/", SPAStaticFiles(directory=str(static_dir), html=True), name="static")

    return app


# Module-level app for `uvicorn app.main:app`.
app = create_app()


def run() -> None:  # pragma: no cover - console entrypoint
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 - server binds all interfaces by design
        port=settings.web_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":  # pragma: no cover
    run()
