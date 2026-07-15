"""Shared application context wiring together all long-lived services.

Stored on `app.state.ctx` and accessed by API routers and the websocket route
via dependency helpers. Created and torn down by the FastAPI lifespan.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import Settings
from .services.control_lease import ControlLease
from .services.decoder import ReceiveOnlyDecoder, build_default_decoder
from .services.recorder import Recorder
from .services.retention import RetentionService
from .services.scan_manager import ScanManager
from .storage.db import Database
from .storage.repositories import Repositories
from .websocket.manager import ConnectionManager


@dataclass
class AppContext:
    settings: Settings
    db: Database
    repos: Repositories
    ws: ConnectionManager
    lease: ControlLease
    scan_manager: ScanManager
    recorder: Recorder
    decoder: ReceiveOnlyDecoder
    retention: RetentionService
    started_at: float = field(default_factory=time.monotonic)

    def uptime_s(self) -> float:
        return round(time.monotonic() - self.started_at, 3)


def build_context(settings: Settings) -> AppContext:
    """Construct all services (without connecting the DB or opening the SDR)."""
    db = Database(settings.database_path)
    repos = Repositories(db)
    ws = ConnectionManager()
    lease = ControlLease()
    scan_manager = ScanManager(settings, repos, ws, lease)
    recorder = Recorder(settings)
    decoder = build_default_decoder()
    retention = RetentionService(settings, repos)
    # Let config changes propagate recording/retention governance at runtime.
    scan_manager.attach_services(recorder, retention)
    return AppContext(
        settings=settings,
        db=db,
        repos=repos,
        ws=ws,
        lease=lease,
        scan_manager=scan_manager,
        recorder=recorder,
        decoder=decoder,
        retention=retention,
    )
