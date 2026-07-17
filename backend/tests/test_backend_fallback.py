"""Fail-loud behaviour when a requested hardware backend is unavailable.

Regression coverage for the silent sim-fallback trap: with SIMULATION_MODE=false
the app used to fall back to the simulator on any hardware error (e.g. a ppm
no-op failure at open) and keep running as if it were a real capture. The
factory must now flag that fallback as degraded, and /api/health must surface it
as HTTP 503 so a container health check fails.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.sdr.factory import create_backend

from .conftest import make_settings


def _hw_settings(tmp_path: Path) -> Settings:
    """Settings that explicitly demand real RTL-SDR hardware."""
    return make_settings(tmp_path).model_copy(
        update={"sdr_backend": "rtlsdr", "simulation_mode": False}
    )


def test_requested_hardware_unavailable_is_degraded(tmp_path: Path) -> None:
    # No dongle/pyrtlsdr in the test env, so rtlsdr construction/open fails.
    sel = create_backend(_hw_settings(tmp_path))

    # App stays runnable (a backend is returned)...
    assert sel.backend is not None
    assert sel.backend.get_info().simulation is True
    # ...but the fallback is flagged loudly with a reason.
    assert sel.degraded is True
    assert sel.requested == "rtlsdr"
    assert sel.reason


def test_simulation_requested_is_not_degraded(tmp_path: Path) -> None:
    sel = create_backend(make_settings(tmp_path))  # sim + simulation_mode=True

    assert sel.backend.get_info().simulation is True
    assert sel.degraded is False
    assert sel.reason is None


async def test_health_reports_503_when_degraded(client, ctx) -> None:  # noqa: ANN001
    # Simulate the factory having fallen back against an explicit HW request.
    ctx.scan_manager._hardware_degraded = True
    ctx.scan_manager._hardware_reason = "Could not set freq. offset to 0 ppm"

    resp = await client.get("/api/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["hardware_degraded"] is True
    assert "ppm" in body["detail"]


async def test_health_ok_when_not_degraded(client) -> None:  # noqa: ANN001
    resp = await client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["hardware_degraded"] is False
