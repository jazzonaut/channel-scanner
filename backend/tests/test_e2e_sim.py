"""End-to-end simulation test: scan finds channels and streams spectrum."""

from __future__ import annotations

import asyncio

from httpx import AsyncClient


async def test_scan_detects_channels_and_flows(client: AsyncClient) -> None:
    start = await client.post("/api/scan/start")
    assert start.status_code == 200
    session_id = start.json()["session_id"]

    # Let the sim run long enough to observe recurring emitters.
    channels: list = []
    for _ in range(30):
        await asyncio.sleep(0.2)
        resp = await client.get("/api/channels")
        channels = resp.json()["channels"]
        if channels:
            break

    assert channels, "expected at least one candidate channel to be detected"
    ch = channels[0]
    assert ch["observation_count"] >= 1
    assert ch["center_hz"] > 0
    assert 0.0 <= ch["confidence"] <= 1.0
    assert ch["status"] in ("active", "recently_active", "inactive")

    # Metrics should show DSP activity.
    metrics = (await client.get("/api/metrics")).json()
    assert metrics["fft_rate_hz"] > 0.0

    # Observations for the channel should exist.
    obs = (await client.get(f"/api/channels/{ch['id']}/observations")).json()
    assert isinstance(obs["observations"], list)

    # Sessions include our run.
    sessions = (await client.get("/api/sessions")).json()["sessions"]
    assert any(s["id"] == session_id for s in sessions)

    await client.post("/api/scan/stop")

    # Events recorded scan_start/stop.
    events = (await client.get("/api/events")).json()["events"]
    kinds = {e["kind"] for e in events}
    assert "scan_start" in kinds
