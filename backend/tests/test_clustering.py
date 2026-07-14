"""Clustering tests: nearby detections merge, distant ones split."""

from __future__ import annotations

from app.signal_processing.clustering import ChannelClusterer
from app.signal_processing.detector import SignalRegion


def _region(center: int, bw: int = 20_000, peak: float = -20.0) -> SignalRegion:
    return SignalRegion(
        center_hz=center,
        bandwidth_hz=bw,
        peak_power_db=peak,
        avg_power_db=peak - 3.0,
        snr_db=peak + 60.0,
        start_hz=center - bw // 2,
        stop_hz=center + bw // 2,
        bin_start=0,
        bin_stop=10,
    )


def test_nearby_regions_form_one_channel() -> None:
    c = ChannelClusterer(proximity_hz=25_000)
    c.ingest(_region(868_000_000), "t0")
    c.ingest(_region(868_010_000), "t1")
    c.ingest(_region(868_005_000), "t2")
    assert len(c.channels) == 1
    ch = c.channels[0]
    assert ch.observation_count == 3
    assert 867_990_000 <= ch.center_hz <= 868_020_000


def test_distant_regions_form_two_channels() -> None:
    c = ChannelClusterer(proximity_hz=25_000)
    c.ingest(_region(868_000_000), "t0")
    c.ingest(_region(869_000_000), "t1")
    assert len(c.channels) == 2


def test_stable_ids_across_updates() -> None:
    c = ChannelClusterer(proximity_hz=25_000)
    first = c.ingest(_region(868_000_000), "t0")
    again = c.ingest(_region(868_002_000), "t1")
    assert first.id == again.id


def test_merge_overlapping_collapses_drifted_channels() -> None:
    c = ChannelClusterer(proximity_hz=5_000)
    a = c.ingest(_region(868_000_000), "t0")
    # Force a second channel just outside proximity, then drift it in.
    b = c.ingest(_region(868_020_000), "t1")
    assert a.id != b.id
    b.center_hz = 868_003_000  # simulate drift within proximity
    c.merge_overlapping()
    assert len(c.channels) == 1
