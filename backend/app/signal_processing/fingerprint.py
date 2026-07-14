"""Non-identifying burst fingerprints.

A fingerprint summarises the *shape* of a recurring emission for de-duplication
and display: center, bandwidth, duration, a coarse power envelope, repetition
interval and relative strength. It deliberately contains NO payload bits and NO
identifying content -- this is a receive-only, privacy-preserving descriptor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BurstFingerprint:
    center_hz: int
    bandwidth_hz: int
    duration_ms: float
    rel_strength_db: float
    repetition_interval_s: float | None
    envelope: list[float]

    def to_dict(self) -> dict[str, object]:
        return {
            "center_hz": self.center_hz,
            "bandwidth_hz": self.bandwidth_hz,
            "duration_ms": self.duration_ms,
            "rel_strength_db": self.rel_strength_db,
            "repetition_interval_s": self.repetition_interval_s,
            "envelope": self.envelope,
        }


def normalize_envelope(power_db_samples: np.ndarray, bins: int = 16) -> list[float]:
    """Reduce a sequence of power samples to a fixed-length 0..1 envelope.

    The envelope captures relative shape only (min-max normalized), never
    absolute levels or payload content.
    """
    if power_db_samples.size == 0:
        return [0.0] * bins
    # Resample to `bins` points via averaging buckets.
    n = power_db_samples.size
    idx = np.linspace(0, n, bins + 1).astype(int)
    reduced = np.empty(bins, dtype=np.float64)
    for i in range(bins):
        lo, hi = idx[i], max(idx[i] + 1, idx[i + 1])
        reduced[i] = float(np.mean(power_db_samples[lo:hi]))
    lo_v, hi_v = float(reduced.min()), float(reduced.max())
    if hi_v - lo_v < 1e-9:
        return [0.0] * bins
    norm = (reduced - lo_v) / (hi_v - lo_v)
    return [round(float(x), 4) for x in norm]


def build_fingerprint(
    *,
    center_hz: int,
    bandwidth_hz: int,
    duration_ms: float,
    peak_power_db: float,
    noise_floor_db: float,
    repetition_interval_s: float | None,
    envelope_samples: np.ndarray | None = None,
    envelope_bins: int = 16,
) -> BurstFingerprint:
    """Construct a non-identifying fingerprint from region statistics."""
    if envelope_samples is not None and envelope_samples.size:
        envelope = normalize_envelope(envelope_samples, envelope_bins)
    else:
        # Fall back to a flat envelope when only scalar stats are available.
        envelope = [1.0] * envelope_bins
    rel = round(float(peak_power_db - noise_floor_db), 3)
    return BurstFingerprint(
        center_hz=int(center_hz),
        bandwidth_hz=int(bandwidth_hz),
        duration_ms=round(float(duration_ms), 3),
        rel_strength_db=rel,
        repetition_interval_s=repetition_interval_s,
        envelope=envelope,
    )
