"""Runtime configurability of scanning-related settings via PUT /api/config.

Everything that affects scanning is tunable from the API/UI at runtime:
display (spectrum fps/bins), recording governance (IQ enable, storage cap),
retention window, and the receiver backend/device/simulation selection.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _acquire_and_version(client: AsyncClient, client_id: str) -> int:
    await client.post("/api/control/acquire", json={"client_id": client_id, "display_name": "Op"})
    cfg = (await client.get("/api/config")).json()
    return int(cfg["version"])


@pytest.mark.asyncio
async def test_display_and_recording_settings_apply(client: AsyncClient, ctx) -> None:  # noqa: ANN001
    version = await _acquire_and_version(client, "op")
    r = await client.put(
        "/api/config",
        json={
            "version": version,
            "client_id": "op",
            "spectrum_fps": 5,
            "spectrum_bins": 512,
            "enable_iq_recording": True,
            "max_iq_storage_gb": 1.0,
            "retention_days": 7,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["spectrum_fps"] == 5
    assert body["spectrum_bins"] == 512
    assert body["enable_iq_recording"] is True
    assert body["retention_days"] == 7
    # Propagated to the live services.
    assert ctx.recorder.enabled is True
    assert ctx.retention._retention_days == 7


@pytest.mark.asyncio
async def test_switching_backend_reconciles_to_sim_without_hardware(
    client: AsyncClient,
    ctx,  # noqa: ANN001
) -> None:
    version = await _acquire_and_version(client, "op")
    r = await client.put(
        "/api/config",
        json={
            "version": version,
            "client_id": "op",
            "backend": "rtlsdr",
            "simulation": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # No dongle in tests: the factory falls back to sim and the live config is
    # reconciled to reflect what actually opened.
    assert body["backend"] == "sim"
    assert body["simulation"] is True


@pytest.mark.asyncio
async def test_invalid_display_values_rejected(client: AsyncClient) -> None:
    version = await _acquire_and_version(client, "op")
    r = await client.put(
        "/api/config",
        json={"version": version, "client_id": "op", "spectrum_fps": 999},
    )
    assert r.status_code == 422
