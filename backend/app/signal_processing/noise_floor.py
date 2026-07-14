"""Adaptive noise-floor estimation.

Combines a robust per-frame estimate (a low percentile of the PSD, which is
insensitive to the presence of signals) with an exponential moving average
(EMA) across frames for temporal stability. NOISE_FLOOR_ALPHA controls the EMA.
"""

from __future__ import annotations

import numpy as np


def frame_noise_floor_db(power_db: np.ndarray, percentile: float = 25.0) -> float:
    """Robust single-frame noise floor: a low percentile of the spectrum.

    Signals occupy a minority of bins and sit above the floor, so a low
    percentile approximates the noise level while ignoring occupied bins.
    """
    if power_db.size == 0:
        return -120.0
    return float(np.percentile(power_db, percentile))


class NoiseFloorEstimator:
    """EMA tracker of the spectrum noise floor (in dB).

    Args:
        alpha: EMA smoothing factor in (0, 1]. Larger = faster adaptation.
        percentile: percentile used for the robust per-frame estimate.
    """

    def __init__(self, alpha: float = 0.05, percentile: float = 25.0) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = float(alpha)
        self.percentile = float(percentile)
        self._value: float | None = None

    @property
    def value(self) -> float:
        """Current smoothed noise floor in dB (-120.0 until first update)."""
        return self._value if self._value is not None else -120.0

    @property
    def initialized(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._value = None

    def update(self, power_db: np.ndarray) -> float:
        """Feed one PSD frame; returns the updated smoothed floor (dB)."""
        frame = frame_noise_floor_db(power_db, self.percentile)
        if self._value is None:
            self._value = frame
        else:
            self._value = (1.0 - self.alpha) * self._value + self.alpha * frame
        return self._value

    def update_scalar(self, frame_floor_db: float) -> float:
        """Feed a precomputed per-frame floor value."""
        if self._value is None:
            self._value = float(frame_floor_db)
        else:
            self._value = (1.0 - self.alpha) * self._value + self.alpha * float(frame_floor_db)
        return self._value
