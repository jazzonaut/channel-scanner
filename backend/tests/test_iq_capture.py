"""Continuous acquisition and triggered rolling-IQ capture regression tests."""

from __future__ import annotations

import threading

import numpy as np

from app.sdr.base import SdrBackend, SdrInfo, TuneRange
from app.services.iq_stream import ContinuousIqStream
from app.services.recorder import Recorder
from app.services.triggered_capture import TriggeredCaptureBuffer


class FiniteBackend(SdrBackend):
    name = "test"

    def __init__(self) -> None:
        self._center_hz = 0
        self._sample_rate = 0
        self.tunes: list[int] = []

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def read_iq(self, n: int) -> np.ndarray:
        return np.arange(n, dtype=np.float32).astype(np.complex64)

    def stream_iq(self, n, callback, stop_event: threading.Event) -> None:  # noqa: ANN001
        for offset in range(3):
            callback(np.full(n, offset, dtype=np.complex64))

    def set_center_freq(self, hz: int) -> None:
        self._center_hz = int(hz)
        self.tunes.append(int(hz))

    def set_sample_rate(self, sps: int) -> None:
        self._sample_rate = int(sps)

    def set_gain(self, gain: str | float) -> None:
        return None

    def set_ppm(self, ppm: int) -> None:
        return None

    def get_info(self) -> SdrInfo:
        raise NotImplementedError

    @property
    def tune_range(self) -> TuneRange:
        return TuneRange(1, 2)


async def test_continuous_stream_assigns_monotonic_sample_positions() -> None:
    backend = FiniteBackend()
    stream = ContinuousIqStream(
        backend,
        center_hz=868_269_000,
        sample_rate=100,
        block_samples=4,
        queue_blocks=4,
    )
    stream.start()
    blocks = [await stream.get(), await stream.get(), await stream.get()]
    stream.stop()

    assert [block.start_sample for block in blocks if block is not None] == [0, 4, 8]
    assert backend.tunes == [868_269_000]
    assert stream.snapshot()["samples_acquired"] == 12


async def test_continuous_stream_exposes_queue_loss_as_a_sequence_gap() -> None:
    stream = ContinuousIqStream(
        FiniteBackend(),
        center_hz=1,
        sample_rate=100,
        block_samples=4,
        queue_blocks=2,
    )
    stream._on_samples(np.zeros(4, np.complex64))
    stream._on_samples(np.zeros(4, np.complex64))
    stream._on_samples(np.zeros(4, np.complex64))

    first = await stream.get()
    assert first is not None
    assert first.start_sample == 4
    assert stream.snapshot()["dropped_blocks"] == 1
    assert stream.snapshot()["dropped_samples"] == 4


def test_trigger_buffer_coalesces_events_with_pre_and_post_iq() -> None:
    capture = TriggeredCaptureBuffer(
        100,
        pre_trigger_s=1.0,
        post_trigger_s=0.5,
        max_capture_s=2.0,
    )
    capture.append(np.arange(100, dtype=np.float32).astype(np.complex64))
    capture.trigger({"sequence": 1, "channel_index": 2})
    capture.append(np.full(20, 2, np.complex64))
    capture.trigger({"sequence": 2, "channel_index": 7})
    capture.append(np.full(50, 3, np.complex64))

    result = capture.pop_ready()
    assert result is not None
    assert result.samples.size == 170
    assert [trigger["channel_index"] for trigger in result.triggers] == [2, 7]
    assert capture.snapshot()["captures_completed"] == 1


def test_trigger_buffer_discards_pending_capture_across_gap() -> None:
    capture = TriggeredCaptureBuffer(100, pre_trigger_s=1, post_trigger_s=1)
    capture.append(np.zeros(100, np.complex64))
    capture.trigger({"sequence": 1})
    capture.discontinuity()

    assert capture.pop_ready() is None
    assert capture.snapshot()["captures_aborted_discontinuity"] == 1
    assert capture.recent(10) is None


def test_recorder_persists_existing_iq_without_reading_backend(test_settings) -> None:  # noqa: ANN001
    recorder = Recorder(test_settings.model_copy(update={"enable_iq_recording": True}))
    annotation = {"core:sample_start": 0, "channel_detector:wavenis_bursts": [{"sequence": 1}]}

    result = recorder.capture_iq(
        np.array([-1 - 1j, 0 + 0j, 1 + 1j], dtype=np.complex64),
        center_hz=868_269_000,
        sample_rate=2_400_000,
        reason="test-trigger",
        fmt="cu8",
        annotations=[annotation],
    )

    assert result.bytes == 6
    assert result.format == "cu8"
    assert result.sigmf_meta["annotations"] == [annotation]
