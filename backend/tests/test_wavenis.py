from __future__ import annotations

import asyncio

import numpy as np
import pytest
from httpx import AsyncClient

from app.signal_processing.wavenis import (
    WAVENIS_CENTER_HZ,
    WAVENIS_CHANNELS_HZ,
    WavenisWidebandAnalyzer,
)


def _capture_with_hops(sample_rate: int = 2_400_000, duration_s: float = 0.12) -> np.ndarray:
    rng = np.random.default_rng(42)
    count = int(sample_rate * duration_s)
    iq = (rng.normal(0, 0.01, count) + 1j * rng.normal(0, 0.01, count)).astype(np.complex64)
    t = np.arange(count, dtype=np.float64) / sample_rate
    for channel, start_s, stop_s in ((2, 0.020, 0.031), (7, 0.048, 0.058), (14, 0.077, 0.089)):
        mask = (t >= start_s) & (t < stop_s)
        offset_hz = WAVENIS_CHANNELS_HZ[channel] - WAVENIS_CENTER_HZ + 4_000
        iq[mask] += (0.25 * np.exp(2j * np.pi * offset_hz * t[mask])).astype(np.complex64)
    return iq


def test_wavenis_grid_fits_one_rtlsdr_window() -> None:
    assert WavenisWidebandAnalyzer.can_observe(WAVENIS_CENTER_HZ, 2_400_000)
    assert not WavenisWidebandAnalyzer.can_observe(WAVENIS_CENTER_HZ, 1_024_000)


def test_wideband_analyzer_recovers_chronological_hops() -> None:
    analyzer = WavenisWidebandAnalyzer(threshold_db=10.0)
    iq = _capture_with_hops()

    # Feed uneven blocks to exercise cross-block carry and burst state.
    events = []
    for block in np.array_split(iq, 5):
        events.extend(analyzer.process(block, center_hz=WAVENIS_CENTER_HZ, sample_rate=2_400_000))

    qualified = [event for event in events if event.qualified]
    assert [event.channel_index for event in qualified] == [2, 7, 14]
    assert all(8.0 <= event.duration_ms <= 14.0 for event in qualified)
    assert all(event.peak_snr_db >= 10.0 for event in qualified)
    assert all(abs(event.freq_offset_hz - 4_000) < 4_000 for event in qualified)


def test_noise_does_not_create_qualified_bursts() -> None:
    rng = np.random.default_rng(7)
    iq = (rng.normal(0, 0.01, 240_000) + 1j * rng.normal(0, 0.01, 240_000)).astype(np.complex64)
    analyzer = WavenisWidebandAnalyzer()
    events = analyzer.process(iq, center_hz=WAVENIS_CENTER_HZ, sample_rate=2_400_000)
    assert not [event for event in events if event.qualified]
    assert analyzer.snapshot()["candidates_flagged"] == 0


def test_measured_centroid_detects_off_grid_signal_in_mask_gap() -> None:
    # 868.010 MHz falls in the dead gap between the old ch4/ch5 100 kHz masks
    # and used to be lost entirely. It must now be detected at its true centre.
    sample_rate = 2_400_000
    count = int(sample_rate * 0.15)
    rng = np.random.default_rng(3)
    iq = (rng.normal(0, 0.01, count) + 1j * rng.normal(0, 0.01, count)).astype(np.complex64)
    t = np.arange(count, dtype=np.float64) / sample_rate
    mask = (t >= 0.05) & (t < 0.09)
    off = 868_010_000 - WAVENIS_CENTER_HZ
    iq[mask] += (0.2 * np.exp(2j * np.pi * off * t[mask])).astype(np.complex64)

    analyzer = WavenisWidebandAnalyzer()
    events = analyzer.process(iq, center_hz=WAVENIS_CENTER_HZ, sample_rate=sample_rate)
    hits = [e for e in events if e.qualified and abs(e.freq_hz - 868_010_000) < 5_000]
    assert hits, "off-grid emitter in the old mask gap was not detected"


def _capture_wideband(sample_rate: int = 2_400_000, duration_s: float = 0.15) -> np.ndarray:
    """A ~60 kHz-wide burst (25 simultaneous tones) on one channel."""
    count = int(sample_rate * duration_s)
    rng = np.random.default_rng(11)
    iq = (rng.normal(0, 0.01, count) + 1j * rng.normal(0, 0.01, count)).astype(np.complex64)
    t = np.arange(count, dtype=np.float64) / sample_rate
    mask = (t >= 0.05) & (t < 0.095)
    base = WAVENIS_CHANNELS_HZ[7] - WAVENIS_CENTER_HZ
    for k in range(-12, 13):
        off = base + k * 2_500
        iq[mask] += (0.05 * np.exp(2j * np.pi * off * t[mask])).astype(np.complex64)
    return iq


def test_wideband_burst_is_flagged_and_persisted_in_snapshot() -> None:
    analyzer = WavenisWidebandAnalyzer()
    iq = _capture_wideband()
    events = analyzer.process(iq, center_hz=WAVENIS_CENTER_HZ, sample_rate=2_400_000)
    flagged = [e for e in events if e.is_candidate]
    assert flagged, "wideband burst should be auto-flagged"
    assert any("wideband" in e.candidate_reasons for e in flagged)
    assert all(e.bandwidth_hz >= 20_000 for e in flagged)
    snap = analyzer.snapshot()
    assert snap["candidates_flagged"] >= 1
    assert len(snap["recent_candidates"]) >= 1


def test_fhss_hop_across_channels_is_flagged() -> None:
    analyzer = WavenisWidebandAnalyzer(threshold_db=10.0)
    events = []
    for block in np.array_split(_capture_with_hops(), 5):
        events.extend(analyzer.process(block, center_hz=WAVENIS_CENTER_HZ, sample_rate=2_400_000))
    # The third distinct channel touched within the window trips the FHSS tell.
    assert any(e.is_candidate and "fhss_hop" in e.candidate_reasons for e in events)


def test_single_narrowband_neighbour_is_not_flagged() -> None:
    # A steady ~2 kHz tone on one channel (like the real ISM neighbours) must
    # never be flagged, or an unattended run fills with false positives.
    sample_rate = 2_400_000
    count = int(sample_rate * 0.2)
    rng = np.random.default_rng(5)
    iq = (rng.normal(0, 0.01, count) + 1j * rng.normal(0, 0.01, count)).astype(np.complex64)
    t = np.arange(count, dtype=np.float64) / sample_rate
    mask = (t >= 0.02) & (t < 0.18)  # long, narrow, single channel
    off = 868_649_000 - WAVENIS_CENTER_HZ
    iq[mask] += (0.2 * np.exp(2j * np.pi * off * t[mask])).astype(np.complex64)
    analyzer = WavenisWidebandAnalyzer()
    events = analyzer.process(iq, center_hz=WAVENIS_CENTER_HZ, sample_rate=sample_rate)
    assert not [e for e in events if e.is_candidate]


@pytest.mark.asyncio
async def test_wavenis_status_endpoint_explains_when_profile_is_required(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/wavenis")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["active"] is False
    assert len(body["grid_hz"]) == 15
    assert "preset" in body["message"]


@pytest.mark.asyncio
async def test_wavenis_profile_runs_inside_scan_loop(client: AsyncClient) -> None:
    await client.post("/api/control/acquire", json={"client_id": "wavenis-test"})
    current = (await client.get("/api/config")).json()
    updated = await client.put(
        "/api/config",
        json={
            "client_id": "wavenis-test",
            "version": current["version"],
            "start_hz": WAVENIS_CHANNELS_HZ[0],
            "end_hz": WAVENIS_CHANNELS_HZ[-1],
            "sample_rate": 2_400_000,
            "dwell_ms": 40,
        },
    )
    assert updated.status_code == 200

    await client.post("/api/scan/start")
    try:
        for _ in range(20):
            status = (await client.get("/api/wavenis")).json()
            if status["frames_processed"] > 0:
                break
            await asyncio.sleep(0.02)
        assert status["configured"] is True
        assert status["active"] is True
        assert status["frames_processed"] > 0
    finally:
        await client.post("/api/scan/stop")
