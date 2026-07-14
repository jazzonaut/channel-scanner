"""Noise-floor estimator tests."""

from __future__ import annotations

import numpy as np

from app.signal_processing.noise_floor import NoiseFloorEstimator, frame_noise_floor_db


def test_frame_floor_ignores_signal_peaks() -> None:
    spectrum = np.full(1024, -60.0)
    spectrum[500:505] = -10.0  # a strong narrowband signal
    floor = frame_noise_floor_db(spectrum, percentile=25.0)
    assert abs(floor - (-60.0)) < 1e-6


def test_ema_converges_towards_frames() -> None:
    est = NoiseFloorEstimator(alpha=0.5)
    frames = [np.full(256, -50.0) for _ in range(20)]
    value = -999.0
    for f in frames:
        value = est.update(f)
    assert abs(value - (-50.0)) < 0.5
    assert est.initialized


def test_alpha_bounds() -> None:
    for bad in (0.0, -0.1, 1.5):
        try:
            NoiseFloorEstimator(alpha=bad)
        except ValueError:
            continue
        raise AssertionError(f"alpha={bad} should have raised")


def test_reset() -> None:
    est = NoiseFloorEstimator(alpha=0.2)
    est.update(np.full(64, -40.0))
    est.reset()
    assert not est.initialized
    assert est.value == -120.0
