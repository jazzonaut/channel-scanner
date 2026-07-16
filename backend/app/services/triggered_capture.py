"""Rolling IQ history and bounded event-triggered capture assembly."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np


@dataclass
class _PendingCapture:
    start_sample: int
    deadline_sample: int
    max_end_sample: int
    chunks: list[np.ndarray]
    triggers: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class TriggeredCapture:
    samples: np.ndarray
    start_sample: int
    end_sample: int
    triggers: list[dict]


class TriggeredCaptureBuffer:
    """Keep pre-trigger IQ and coalesce nearby events into one capture."""

    def __init__(
        self,
        sample_rate: int,
        *,
        pre_trigger_s: float = 2.0,
        post_trigger_s: float = 1.0,
        max_capture_s: float = 5.0,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.pre_trigger_samples = max(1, int(self.sample_rate * pre_trigger_s))
        self.post_trigger_samples = max(1, int(self.sample_rate * post_trigger_s))
        self.max_capture_samples = max(1, int(self.sample_rate * max_capture_s))
        self._history: deque[np.ndarray] = deque()
        self._history_samples = 0
        self._sample_cursor = 0
        self._pending: _PendingCapture | None = None
        self._completed = 0
        self._aborted_discontinuities = 0

    def append(self, samples: np.ndarray) -> None:
        iq = np.asarray(samples, dtype=np.complex64)
        if not iq.flags.owndata:
            iq = iq.copy()
        if self._pending is not None:
            self._pending.chunks.append(iq)
        self._history.append(iq)
        self._history_samples += int(iq.size)
        self._sample_cursor += int(iq.size)
        self._trim_history()

    def _trim_history(self) -> None:
        while self._history and self._history_samples > self.pre_trigger_samples:
            excess = self._history_samples - self.pre_trigger_samples
            first = self._history[0]
            if excess >= first.size:
                self._history.popleft()
                self._history_samples -= int(first.size)
                continue
            self._history[0] = first[excess:].copy()
            self._history_samples -= excess
            break

    def trigger(self, evidence: dict) -> None:
        if self._pending is None:
            start = self._sample_cursor - self._history_samples
            self._pending = _PendingCapture(
                start_sample=start,
                deadline_sample=self._sample_cursor + self.post_trigger_samples,
                max_end_sample=start + self.max_capture_samples,
                chunks=list(self._history),
            )
        else:
            self._pending.deadline_sample = min(
                self._pending.max_end_sample,
                self._sample_cursor + self.post_trigger_samples,
            )
        self._pending.triggers.append(dict(evidence))

    def pop_ready(self) -> TriggeredCapture | None:
        pending = self._pending
        if pending is None or self._sample_cursor < pending.deadline_sample:
            return None
        available = np.concatenate(pending.chunks) if pending.chunks else np.empty(0, np.complex64)
        wanted = min(available.size, pending.max_end_sample - pending.start_sample)
        samples = available[:wanted].copy()
        result = TriggeredCapture(
            samples=samples,
            start_sample=pending.start_sample,
            end_sample=pending.start_sample + int(samples.size),
            triggers=list(pending.triggers),
        )
        self._pending = None
        self._completed += 1
        return result

    def discontinuity(self) -> None:
        """Drop history that cannot safely be joined across a sample gap."""
        if self._pending is not None:
            self._aborted_discontinuities += 1
        self._pending = None
        self._history.clear()
        self._history_samples = 0

    def recent(self, duration_ms: int) -> np.ndarray | None:
        """Return a copy of recent contiguous IQ, or None if not yet buffered."""
        wanted = max(1, int(self.sample_rate * duration_ms / 1000.0))
        if self._history_samples < wanted:
            return None
        joined = np.concatenate(tuple(self._history))
        return joined[-wanted:].copy()

    def reset(self) -> None:
        self._history.clear()
        self._history_samples = 0
        self._sample_cursor = 0
        self._pending = None
        self._completed = 0
        self._aborted_discontinuities = 0

    def snapshot(self) -> dict[str, int | float | bool]:
        return {
            "buffered_seconds": round(self._history_samples / self.sample_rate, 3),
            "pre_trigger_seconds": round(self.pre_trigger_samples / self.sample_rate, 3),
            "post_trigger_seconds": round(self.post_trigger_samples / self.sample_rate, 3),
            "max_capture_seconds": round(self.max_capture_samples / self.sample_rate, 3),
            "capture_pending": self._pending is not None,
            "pending_triggers": len(self._pending.triggers) if self._pending else 0,
            "captures_completed": self._completed,
            "captures_aborted_discontinuity": self._aborted_discontinuities,
        }
