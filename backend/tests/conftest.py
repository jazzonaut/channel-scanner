"""Shared pytest fixtures. All tests run in SIMULATION_MODE with a temp DB."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.storage.db import Database
from app.storage.migrations import apply_migrations
from app.storage.repositories import Repositories


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        sdr_backend="sim",
        simulation_mode=True,
        database_path=str(tmp_path / "db.sqlite3"),
        recording_path=str(tmp_path / "rec"),
        log_dir=str(tmp_path / "logs"),
        enable_iq_recording=False,
        scan_start_hz=867_000_000,
        scan_end_hz=870_000_000,
        sdr_sample_rate=2_400_000,
        scan_dwell_ms=40,
        fft_size=2048,
        spectrum_fps=50,
        spectrum_bins=512,
        detection_threshold_db=6.0,
        noise_floor_alpha=0.1,
    )


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def app(test_settings: Settings):
    return create_app(test_settings)


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    # Run the app lifespan so the AppContext (DB, scan manager) is initialised.
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def ctx(app, client):  # noqa: ANN001, ANN201 - test fixture
    """The live AppContext (DB, scan manager, recorder, retention) during lifespan."""
    return app.state.ctx


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(str(tmp_path / "unit.sqlite3"))
    await database.connect()
    await apply_migrations(database)
    try:
        yield database
    finally:
        await database.close()


@pytest_asyncio.fixture
async def repos(db: Database) -> Repositories:
    return Repositories(db)
