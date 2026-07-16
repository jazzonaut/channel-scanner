"""Time-resolved wideband evidence extraction for the Wavenis 868 grid.

The candidate 15-channel grid spans only 1.4 MHz, so a 2.4 MS/s RTL-SDR can
observe it continuously in one parked window. This module deliberately stops
at RF evidence: it tracks per-channel noise, burst timing, hop chronology and
coarse centring error. It does not claim protocol identity or decode payloads.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field

import numpy as np

WAVENIS_CHANNELS_HZ = tuple(867_569_000 + 100_000 * index for index in range(15))
WAVENIS_CENTER_HZ = WAVENIS_CHANNELS_HZ[7]
WAVENIS_GRID_GUARD_HZ = 40_000


@dataclass(frozen=True)
class WavenisBurst:
    sequence: int
    channel_index: int
    freq_hz: int
    start_s: float
    duration_ms: float
    peak_snr_db: float
    noise_db: float
    above_frames: int
    qualified: bool
    freq_offset_hz: float

    def to_dict(self) -> dict[str, int | float | bool]:
        return asdict(self)


@dataclass
class _ChannelState:
    noise_db: float | None = None
    active: bool = False
    start_sample: int = 0
    last_above_end_sample: int = 0
    below_frames: int = 0
    above_frames: int = 0
    peak_db: float = -200.0
    centroid_offsets: list[float] = field(default_factory=list)
    observations: int = 0
    qualified_observations: int = 0
    last_seen_s: float | None = None
    peak_snr_db: float = 0.0


class WavenisWidebandAnalyzer:
    """Extract a 15-channel power timeline from consecutive complex IQ blocks."""

    def __init__(
        self,
        *,
        frame_samples: int = 2048,
        channel_bandwidth_hz: int = 60_000,
        threshold_db: float = 12.0,
        noise_alpha: float = 0.02,
        holdoff_frames: int = 2,
        min_qualified_frames: int = 2,
        recent_limit: int = 200,
    ) -> None:
        self.frame_samples = int(frame_samples)
        self.channel_bandwidth_hz = int(channel_bandwidth_hz)
        self.threshold_db = float(threshold_db)
        self.noise_alpha = float(noise_alpha)
        self.holdoff_frames = int(holdoff_frames)
        self.min_qualified_frames = int(min_qualified_frames)
        self._states = [_ChannelState() for _ in WAVENIS_CHANNELS_HZ]
        self._recent: deque[WavenisBurst] = deque(maxlen=recent_limit)
        self._pending = np.empty(0, dtype=np.complex64)
        self._sample_cursor = 0
        self._sequence = 0
        self._sample_rate = 0
        self._center_hz = 0
        self._frames_processed = 0

    @staticmethod
    def can_observe(center_hz: int, sample_rate: int) -> bool:
        half = int(sample_rate) // 2
        return (
            int(center_hz) - half <= WAVENIS_CHANNELS_HZ[0] - WAVENIS_GRID_GUARD_HZ
            and int(center_hz) + half >= WAVENIS_CHANNELS_HZ[-1] + WAVENIS_GRID_GUARD_HZ
        )

    def reset(self) -> None:
        recent_limit = self._recent.maxlen or 200
        self._states = [_ChannelState() for _ in WAVENIS_CHANNELS_HZ]
        self._recent = deque(maxlen=recent_limit)
        self._pending = np.empty(0, dtype=np.complex64)
        self._sample_cursor = 0
        self._sequence = 0
        self._sample_rate = 0
        self._center_hz = 0
        self._frames_processed = 0

    def process(self, iq: np.ndarray, *, center_hz: int, sample_rate: int) -> list[WavenisBurst]:
        if not self.can_observe(center_hz, sample_rate):
            return []
        if self._sample_rate and (self._sample_rate != sample_rate or self._center_hz != center_hz):
            self.reset()
        self._sample_rate = int(sample_rate)
        self._center_hz = int(center_hz)

        samples = np.asarray(iq, dtype=np.complex64)
        if self._pending.size:
            samples = np.concatenate((self._pending, samples))
        frame_count = samples.size // self.frame_samples
        if frame_count == 0:
            self._pending = samples.copy()
            return []
        used = frame_count * self.frame_samples
        frames = samples[:used].reshape(frame_count, self.frame_samples)
        self._pending = samples[used:].copy()

        window = np.hanning(self.frame_samples).astype(np.float32)
        spectrum = np.fft.fftshift(np.fft.fft(frames * window, axis=1), axes=1)
        power = np.abs(spectrum) ** 2
        offsets = np.fft.fftshift(np.fft.fftfreq(self.frame_samples, d=1.0 / sample_rate))
        absolute_freqs = offsets + float(center_hz)

        channel_power_db = np.empty((frame_count, len(WAVENIS_CHANNELS_HZ)), dtype=np.float64)
        channel_centroids = np.empty_like(channel_power_db)
        half_band = self.channel_bandwidth_hz / 2.0
        for channel_index, channel_hz in enumerate(WAVENIS_CHANNELS_HZ):
            mask = np.abs(absolute_freqs - channel_hz) <= half_band
            band_power = power[:, mask]
            linear = np.mean(band_power, axis=1) + 1e-20
            channel_power_db[:, channel_index] = 10.0 * np.log10(linear)
            weighted = np.sum(band_power * absolute_freqs[mask], axis=1) / np.sum(
                band_power + 1e-20, axis=1
            )
            channel_centroids[:, channel_index] = weighted - channel_hz

        # Seed unseen channels from a robust within-block percentile. This lets
        # quiet frames establish the floor even when the block also holds a burst.
        for channel_index, state in enumerate(self._states):
            if state.noise_db is None:
                state.noise_db = float(np.percentile(channel_power_db[:, channel_index], 20.0))

        emitted: list[WavenisBurst] = []
        for frame_index in range(frame_count):
            frame_start = self._sample_cursor + frame_index * self.frame_samples
            frame_end = frame_start + self.frame_samples
            for channel_index, channel_hz in enumerate(WAVENIS_CHANNELS_HZ):
                state = self._states[channel_index]
                assert state.noise_db is not None
                value_db = float(channel_power_db[frame_index, channel_index])
                above = value_db >= state.noise_db + self.threshold_db

                if above:
                    if not state.active:
                        state.active = True
                        state.start_sample = frame_start
                        state.above_frames = 0
                        state.peak_db = value_db
                        state.centroid_offsets = []
                    state.last_above_end_sample = frame_end
                    state.below_frames = 0
                    state.above_frames += 1
                    state.peak_db = max(state.peak_db, value_db)
                    state.centroid_offsets.append(
                        float(channel_centroids[frame_index, channel_index])
                    )
                    continue

                if state.active:
                    state.below_frames += 1
                    if state.below_frames >= self.holdoff_frames:
                        burst = self._finish_burst(channel_index, channel_hz, state, sample_rate)
                        self._recent.append(burst)
                        emitted.append(burst)
                    continue

                # Adapt only while inactive. Clamp upward movement so repeated
                # impulsive energy cannot quickly redefine itself as the floor.
                delta = float(np.clip(value_db - state.noise_db, -3.0, 0.25))
                state.noise_db += self.noise_alpha * delta

        self._sample_cursor += used
        self._frames_processed += frame_count
        return emitted

    def _finish_burst(
        self,
        channel_index: int,
        channel_hz: int,
        state: _ChannelState,
        sample_rate: int,
    ) -> WavenisBurst:
        self._sequence += 1
        duration_samples = max(0, state.last_above_end_sample - state.start_sample)
        duration_ms = duration_samples / sample_rate * 1000.0
        peak_snr = state.peak_db - (state.noise_db or state.peak_db)
        qualified = state.above_frames >= self.min_qualified_frames
        offset = float(np.median(state.centroid_offsets)) if state.centroid_offsets else 0.0
        burst = WavenisBurst(
            sequence=self._sequence,
            channel_index=channel_index,
            freq_hz=channel_hz,
            start_s=state.start_sample / sample_rate,
            duration_ms=round(duration_ms, 3),
            peak_snr_db=round(peak_snr, 3),
            noise_db=round(state.noise_db or -120.0, 3),
            above_frames=state.above_frames,
            qualified=qualified,
            freq_offset_hz=round(offset, 1),
        )
        state.observations += 1
        state.qualified_observations += int(qualified)
        state.last_seen_s = burst.start_s
        state.peak_snr_db = max(state.peak_snr_db, peak_snr)
        state.active = False
        state.below_frames = 0
        state.above_frames = 0
        state.centroid_offsets = []
        return burst

    def snapshot(self) -> dict[str, object]:
        channels = []
        for index, (freq_hz, state) in enumerate(
            zip(WAVENIS_CHANNELS_HZ, self._states, strict=True)
        ):
            channels.append(
                {
                    "index": index,
                    "freq_hz": freq_hz,
                    "noise_db": round(state.noise_db, 3) if state.noise_db is not None else None,
                    "active": state.active,
                    "observations": state.observations,
                    "qualified_observations": state.qualified_observations,
                    "last_seen_s": state.last_seen_s,
                    "peak_snr_db": round(state.peak_snr_db, 3),
                }
            )
        return {
            "center_hz": WAVENIS_CENTER_HZ,
            "grid_hz": list(WAVENIS_CHANNELS_HZ),
            "threshold_db": self.threshold_db,
            "frame_ms": round(self.frame_samples / self._sample_rate * 1000.0, 3)
            if self._sample_rate
            else None,
            "frames_processed": self._frames_processed,
            "channels": channels,
            "recent_bursts": [burst.to_dict() for burst in self._recent],
        }
