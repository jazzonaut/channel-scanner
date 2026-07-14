"""Recurrence / burst-timing analysis.

Tracks the arrival timestamps of detections belonging to a candidate channel
and estimates: the recurrence interval (median inter-arrival time between
distinct bursts) and burst-duration statistics. A "burst" is a maximal run of
consecutive detections; a gap larger than `gap_factor * dwell` starts a new one.

Timestamps are epoch seconds (float). Pure, side-effect-free helpers plus a
small stateful tracker.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class RecurrenceStats:
    recurrence_interval_s: float | None
    typical_burst_ms: float | None
    burst_count: int
    interval_jitter_s: float | None


@dataclass
class RecurrenceTracker:
    """Accumulate detection timestamps for one channel and derive timing.

    Args:
        gap_seconds: minimum silent gap that separates two distinct bursts.
        max_events: cap on retained timestamps (ring buffer semantics).
    """

    gap_seconds: float = 1.0
    max_events: int = 512
    _arrivals: list[float] = field(default_factory=list)

    def add(self, ts_epoch: float) -> None:
        self._arrivals.append(float(ts_epoch))
        if len(self._arrivals) > self.max_events:
            self._arrivals = self._arrivals[-self.max_events :]

    def _bursts(self) -> list[tuple[float, float]]:
        """Return (start_ts, end_ts) for each contiguous burst."""
        if not self._arrivals:
            return []
        arrivals = sorted(self._arrivals)
        bursts: list[tuple[float, float]] = []
        start = prev = arrivals[0]
        for t in arrivals[1:]:
            if t - prev > self.gap_seconds:
                bursts.append((start, prev))
                start = t
            prev = t
        bursts.append((start, prev))
        return bursts

    def stats(self) -> RecurrenceStats:
        bursts = self._bursts()
        if not bursts:
            return RecurrenceStats(None, None, 0, None)

        # Burst durations (ms). Single-sample bursts have ~0 measured duration;
        # report a small nominal value so downstream code has a number.
        durations_ms = [max(0.0, (end - start) * 1000.0) for start, end in bursts]
        typical_burst_ms: float | None
        if durations_ms:
            typical_burst_ms = round(statistics.median(durations_ms), 3)
        else:
            typical_burst_ms = None

        # Recurrence interval = median gap between burst starts.
        starts = [b[0] for b in bursts]
        interval: float | None = None
        jitter: float | None = None
        if len(starts) >= 2:
            gaps = [b - a for a, b in zip(starts[:-1], starts[1:], strict=False)]
            interval = round(statistics.median(gaps), 3)
            if len(gaps) >= 2:
                jitter = round(statistics.pstdev(gaps), 3)

        return RecurrenceStats(
            recurrence_interval_s=interval,
            typical_burst_ms=typical_burst_ms,
            burst_count=len(bursts),
            interval_jitter_s=jitter,
        )


def estimate_recurrence(
    arrivals_epoch: list[float], *, gap_seconds: float = 1.0
) -> RecurrenceStats:
    """Stateless convenience wrapper around RecurrenceTracker."""
    tracker = RecurrenceTracker(gap_seconds=gap_seconds)
    for t in arrivals_epoch:
        tracker.add(t)
    return tracker.stats()
