"""Recurrence-interval and burst-duration estimation tests."""

from __future__ import annotations

from app.signal_processing.recurrence import RecurrenceTracker, estimate_recurrence


def test_regular_bursts_yield_interval() -> None:
    # Bursts at t=0,4,8,12s; each burst is two closely-spaced samples.
    arrivals: list[float] = []
    for start in (0.0, 4.0, 8.0, 12.0):
        arrivals.extend([start, start + 0.05])
    stats = estimate_recurrence(arrivals, gap_seconds=1.0)
    assert stats.burst_count == 4
    assert stats.recurrence_interval_s is not None
    assert abs(stats.recurrence_interval_s - 4.0) < 0.2


def test_single_burst_has_no_interval() -> None:
    stats = estimate_recurrence([1.0, 1.05, 1.1], gap_seconds=1.0)
    assert stats.burst_count == 1
    assert stats.recurrence_interval_s is None


def test_burst_duration_measured() -> None:
    tracker = RecurrenceTracker(gap_seconds=1.0)
    for t in (0.0, 0.1, 0.2):  # a single 200 ms burst
        tracker.add(t)
    stats = tracker.stats()
    assert stats.burst_count == 1
    assert stats.typical_burst_ms is not None
    assert abs(stats.typical_burst_ms - 200.0) < 1.0


def test_ring_buffer_cap() -> None:
    tracker = RecurrenceTracker(gap_seconds=1.0, max_events=10)
    for i in range(100):
        tracker.add(float(i))
    # Only the last 10 arrivals retained.
    assert len(tracker._arrivals) == 10
