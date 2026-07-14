"""Occupied-region detection from a power spectrum.

Given a PSD (freqs + power_db) and a noise floor, find contiguous runs of bins
above an adaptive threshold, merge runs separated by small gaps, and summarise
each merged region as a SignalRegion (center, bandwidth, peak/avg power, SNR).

A detected region is an *inferred* occupied slice of spectrum, not a licensed
protocol channel.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SignalRegion:
    """A contiguous occupied region of spectrum."""

    center_hz: int
    bandwidth_hz: int
    peak_power_db: float
    avg_power_db: float
    snr_db: float
    start_hz: int
    stop_hz: int
    bin_start: int
    bin_stop: int  # inclusive


def _contiguous_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return (start, stop_inclusive) index pairs for True runs in a bool mask."""
    if mask.size == 0 or not mask.any():
        return []
    idx = np.flatnonzero(mask)
    splits = np.flatnonzero(np.diff(idx) > 1)
    runs: list[tuple[int, int]] = []
    start = idx[0]
    prev = idx[0]
    for s in splits:
        end = idx[s]
        runs.append((int(start), int(end)))
        start = idx[s + 1]
        prev = start
    runs.append((int(start), int(idx[-1])))
    _ = prev
    return runs


def _merge_runs(runs: list[tuple[int, int]], max_gap_bins: int) -> list[tuple[int, int]]:
    """Merge runs separated by <= max_gap_bins empty bins."""
    if not runs:
        return []
    runs = sorted(runs)
    merged: list[tuple[int, int]] = [runs[0]]
    for start, stop in runs[1:]:
        pstart, pstop = merged[-1]
        if start - pstop - 1 <= max_gap_bins:
            merged[-1] = (pstart, max(pstop, stop))
        else:
            merged.append((start, stop))
    return merged


def detect_regions(
    freqs_hz: np.ndarray,
    power_db: np.ndarray,
    *,
    noise_floor_db: float,
    threshold_db: float = 6.0,
    min_bandwidth_hz: float = 0.0,
    merge_gap_hz: float = 0.0,
) -> list[SignalRegion]:
    """Detect occupied regions in a PSD frame.

    Args:
        freqs_hz: ascending absolute frequency per bin.
        power_db: power per bin (dB).
        noise_floor_db: current smoothed noise floor (dB).
        threshold_db: dB above the noise floor a bin must exceed.
        min_bandwidth_hz: drop regions narrower than this.
        merge_gap_hz: merge regions separated by gaps <= this width.

    Returns:
        List of SignalRegion sorted by center frequency.
    """
    if power_db.size == 0 or freqs_hz.size != power_db.size:
        return []

    bin_width = float(freqs_hz[1] - freqs_hz[0]) if freqs_hz.size >= 2 else 1.0
    bin_width = abs(bin_width) or 1.0

    threshold = noise_floor_db + threshold_db
    mask = power_db >= threshold

    max_gap_bins = int(max(0, round(merge_gap_hz / bin_width)))
    runs = _merge_runs(_contiguous_runs(mask), max_gap_bins)

    regions: list[SignalRegion] = []
    for bstart, bstop in runs:
        seg_power = power_db[bstart : bstop + 1]
        seg_freqs = freqs_hz[bstart : bstop + 1]
        start_hz = float(seg_freqs[0] - bin_width / 2.0)
        stop_hz = float(seg_freqs[-1] + bin_width / 2.0)
        bandwidth_hz = stop_hz - start_hz
        if bandwidth_hz < min_bandwidth_hz:
            continue

        peak = float(np.max(seg_power))
        # Average in the linear domain then back to dB for a fair mean power.
        avg = float(10.0 * np.log10(np.mean(np.power(10.0, seg_power / 10.0))))
        peak_bin = int(bstart + np.argmax(seg_power))
        center_hz = float(freqs_hz[peak_bin])
        snr = peak - noise_floor_db

        regions.append(
            SignalRegion(
                center_hz=int(round(center_hz)),
                bandwidth_hz=int(round(bandwidth_hz)),
                peak_power_db=round(peak, 3),
                avg_power_db=round(avg, 3),
                snr_db=round(snr, 3),
                start_hz=int(round(start_hz)),
                stop_hz=int(round(stop_hz)),
                bin_start=bstart,
                bin_stop=bstop,
            )
        )

    regions.sort(key=lambda r: r.center_hz)
    return regions
