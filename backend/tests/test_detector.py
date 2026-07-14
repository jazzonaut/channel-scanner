"""Detector tests: contiguous-bin grouping and region summary."""

from __future__ import annotations

import numpy as np

from app.signal_processing.detector import _contiguous_runs, _merge_runs, detect_regions


def _freqs(n: int, start: float = 100_000_000.0, step: float = 1_000.0) -> np.ndarray:
    return start + np.arange(n) * step


def test_contiguous_runs() -> None:
    mask = np.array([0, 1, 1, 0, 0, 1, 0, 1, 1, 1], dtype=bool)
    runs = _contiguous_runs(mask)
    assert runs == [(1, 2), (5, 5), (7, 9)]


def test_merge_runs_within_gap() -> None:
    runs = [(1, 2), (4, 5), (10, 12)]
    merged = _merge_runs(runs, max_gap_bins=1)
    assert merged == [(1, 5), (10, 12)]


def test_detect_single_region() -> None:
    n = 512
    power = np.full(n, -60.0)
    power[200:210] = -20.0  # 10-bin signal, 30 dB above floor
    freqs = _freqs(n)
    regions = detect_regions(freqs, power, noise_floor_db=-60.0, threshold_db=6.0)
    assert len(regions) == 1
    r = regions[0]
    assert r.bin_start == 200 and r.bin_stop == 209
    # center near the middle of the occupied bins
    assert 100_000_000 + 200 * 1000 <= r.center_hz <= 100_000_000 + 209 * 1000
    assert r.snr_db > 30.0
    assert r.bandwidth_hz > 0


def test_detect_two_regions_separated() -> None:
    n = 512
    power = np.full(n, -70.0)
    power[100:105] = -30.0
    power[300:308] = -25.0
    freqs = _freqs(n)
    regions = detect_regions(freqs, power, noise_floor_db=-70.0, threshold_db=6.0, merge_gap_hz=0.0)
    assert len(regions) == 2
    assert regions[0].center_hz < regions[1].center_hz


def test_merge_gap_joins_close_regions() -> None:
    n = 512
    power = np.full(n, -70.0)
    power[100:104] = -30.0
    power[106:110] = -30.0  # 2-bin gap between the two
    freqs = _freqs(n)
    merged = detect_regions(
        freqs, power, noise_floor_db=-70.0, threshold_db=6.0, merge_gap_hz=3_000.0
    )
    assert len(merged) == 1


def test_no_regions_below_threshold() -> None:
    power = np.full(256, -60.0)
    regions = detect_regions(_freqs(256), power, noise_floor_db=-60.0, threshold_db=6.0)
    assert regions == []
