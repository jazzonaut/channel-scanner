"""Single-owner continuous IQ acquisition with observable continuity.

The worker is the only code allowed to read a streaming SDR. Each acquired
block receives a monotonic sample position before it enters the bounded queue,
so downstream DSP can detect queue loss instead of silently joining unrelated
sample ranges.
"""

from __future__ import annotations

import asyncio
import contextlib
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from ..sdr.base import SdrBackend


@dataclass(frozen=True)
class IqBlock:
    start_sample: int
    samples: np.ndarray
    captured_monotonic: float

    @property
    def end_sample(self) -> int:
        return self.start_sample + int(self.samples.size)


class ContinuousIqStream:
    """Own one backend stream and bridge its callback into an async consumer."""

    def __init__(
        self,
        backend: SdrBackend,
        *,
        center_hz: int,
        sample_rate: int,
        block_samples: int,
        queue_blocks: int = 8,
    ) -> None:
        self._backend = backend
        self.center_hz = int(center_hz)
        self.sample_rate = int(sample_rate)
        self.block_samples = int(block_samples)
        self._queue: queue.Queue[IqBlock | None] = queue.Queue(maxsize=max(2, queue_blocks))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sample_cursor = 0
        self._last_callback_at: float | None = None
        self._last_block_samples = 0
        self._blocks_acquired = 0
        self._samples_acquired = 0
        self._dropped_blocks = 0
        self._dropped_samples = 0
        self._timing_gaps = 0
        self._estimated_gap_samples = 0
        self._error: str | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._backend.set_sample_rate(self.sample_rate)
        self._backend.set_center_freq(self.center_hz)
        self._thread = threading.Thread(target=self._run, name="sdr-iq-stream", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._backend.stream_iq(self.block_samples, self._on_samples, self._stop_event)
        except Exception as exc:  # noqa: BLE001 - surfaced through status telemetry
            if not self._stop_event.is_set():
                self._error = str(exc)
        finally:
            self._offer_sentinel()

    def _on_samples(self, samples: np.ndarray) -> None:
        if self._stop_event.is_set():
            return
        now = time.monotonic()
        # Own the callback buffer: native libraries are free to reuse their
        # storage as soon as the callback returns.
        iq = np.asarray(samples, dtype=np.complex64).copy()

        if self._last_callback_at is not None and self._last_block_samples:
            expected_s = self._last_block_samples / self.sample_rate
            elapsed_s = now - self._last_callback_at
            excess_s = elapsed_s - expected_s
            if excess_s > max(0.005, expected_s * 0.5):
                self._timing_gaps += 1
                self._estimated_gap_samples += max(0, int(round(excess_s * self.sample_rate)))
        self._last_callback_at = now
        self._last_block_samples = int(iq.size)

        block = IqBlock(self._sample_cursor, iq, now)
        self._sample_cursor = block.end_sample
        self._blocks_acquired += 1
        self._samples_acquired += int(iq.size)
        try:
            self._queue.put_nowait(block)
        except queue.Full:
            # Stay close to live time. Discard the oldest queued block; its
            # sequence number will expose the discontinuity to the consumer.
            try:
                dropped = self._queue.get_nowait()
            except queue.Empty:
                dropped = None
            if dropped is not None:
                self._dropped_blocks += 1
                self._dropped_samples += int(dropped.samples.size)
            self._queue.put_nowait(block)

    async def get(self) -> IqBlock | None:
        return await asyncio.to_thread(self._queue.get)

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        with contextlib.suppress(Exception):
            self._backend.cancel_stream()
        self._offer_sentinel()
        self._thread.join(timeout=2.0)
        self._thread = None

    def _offer_sentinel(self) -> None:
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            with contextlib.suppress(queue.Empty):
                self._queue.get_nowait()
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(None)

    def snapshot(self) -> dict[str, int | float | str | None]:
        return {
            "mode": "native_continuous",
            "blocks_acquired": self._blocks_acquired,
            "samples_acquired": self._samples_acquired,
            "sample_cursor": self._sample_cursor,
            "queue_depth": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "dropped_blocks": self._dropped_blocks,
            "dropped_samples": self._dropped_samples,
            "timing_gaps": self._timing_gaps,
            "estimated_gap_samples": self._estimated_gap_samples,
            "error": self._error,
        }
