"""Time-resolved wideband evidence extraction for the Wavenis 868 grid.

The candidate 15-channel grid spans only 1.4 MHz, so a 2.4 MS/s RTL-SDR can
observe it continuously in one parked window. This module deliberately stops
at RF evidence: it tracks per-bin noise, burst timing, hop chronology and
measured centre frequency. It does not claim protocol identity or decode
payloads.

Detection is **grid-free**. Earlier revisions sliced the window into 15 fixed
100 kHz-spaced channels with 60 kHz masks; that left 40 kHz dead gaps between
masks (real emitters landing there were never seen) and forced every burst
onto a grid centre (fabricating large frequency offsets and lumping distinct
tones together). We now detect occupied regions across the whole observable
span from a per-bin noise floor and report each burst at its **measured**
power-weighted centroid. The nominal 15-channel grid is retained only as a
reference label: ``channel_index`` is the nearest grid channel and
``freq_offset_hz`` is how far the measured centre sits from it -- useful for
checking the §42 bench-grid hypothesis, but no longer used to find signals.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field

import numpy as np

WAVENIS_CHANNELS_HZ = tuple(867_569_000 + 100_000 * index for index in range(15))
WAVENIS_CENTER_HZ = WAVENIS_CHANNELS_HZ[7]
WAVENIS_GRID_GUARD_HZ = 40_000
_GRID_HZ = np.asarray(WAVENIS_CHANNELS_HZ, dtype=np.float64)
_GRID_SPACING_HZ = 100_000

# --- Wavenis candidate fingerprint (see wavenis_868_technical_reference.md) ---
# A burst is auto-flagged as a likely-meter candidate when it looks unlike the
# steady narrowband ISM neighbours and like the Wavenis signature: a ~1.1 s long
# wake-up (§10.1) or a wide (~50 kHz GFSK, §40) occupied bandwidth. These two
# tells are robust in a busy band: duration is immune to spectral leakage and to
# concurrent neighbours, and the bandwidth is measured at a fixed level below the
# peak so a strong *narrowband* tone does not read as wide.
#
# NOTE: a naive "fast hop across channels" (FHSS) tell was removed -- in a real
# busy 868 band it fired on concurrent independent neighbours (each parked on its
# own channel) rather than one emitter actually hopping, flooding the log. Real
# FHSS detection needs single-emitter tracking (a signal leaving A as it appears
# on B) and is deferred until we have a cleaner capture to model it on.
LONG_WAKEUP_MS = (900.0, 1400.0)  # §10.1 default long wake-up ~1100 ms
SHORT_WAKEUP_MS = (35.0, 70.0)  # §10.2 fixed short wake-up 50 ms
WIDEBAND_MIN_HZ = 30_000  # neighbours read <10 kHz at -10 dB; Wavenis ~50 kHz
WIDEBAND_MIN_DURATION_MS = 20.0  # ignore width on very short bursts (edge splatter)
OCCUPIED_BW_DB = 10.0  # bandwidth measured this far below a region's peak
CANDIDATE_MIN_SCORE = 2.0  # total weighted score to flag a candidate

# Novelty filter: the meter is RARE, so a frequency that re-flags again and
# again is a fixed installation (like the dual-tone 868.1 neighbour), not a
# meter. Flag each frequency bucket only a few times, then suppress-and-count
# it so a persistent emitter cannot flood the durable log over a long run.
CANDIDATE_BUCKET_HZ = 50_000  # frequency bucket width for the novelty filter
CANDIDATE_PERSISTENT_AFTER = 2  # flag a bucket this many times, then suppress


def _nearest_grid_index(freq_hz: float) -> int:
    """Nearest nominal grid channel to a measured frequency (label only)."""
    return int(np.argmin(np.abs(_GRID_HZ - float(freq_hz))))


@dataclass(frozen=True)
class WavenisBurst:
    sequence: int
    channel_index: int  # nearest nominal grid channel (reference label only)
    freq_hz: int  # measured power-weighted centre frequency
    start_s: float
    duration_ms: float
    bandwidth_hz: int  # measured occupied bandwidth (peak region span)
    peak_snr_db: float
    noise_db: float
    above_frames: int
    qualified: bool
    freq_offset_hz: float  # measured centre minus nearest grid channel
    candidate_reasons: tuple[str, ...] = ()
    candidate_score: float = 0.0
    is_candidate: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class _ChannelState:
    """Per-grid-channel tally, keyed by nearest measured centre (display only)."""

    noise_db: float | None = None
    observations: int = 0
    qualified_observations: int = 0
    last_seen_s: float | None = None
    peak_snr_db: float = 0.0


@dataclass
class _Track:
    """An in-progress emission being followed across frames by frequency."""

    start_sample: int
    last_above_end_sample: int
    center_hz: float
    peak_db: float
    peak_snr_db: float
    above_frames: int = 0
    below_frames: int = 0
    centroids: list[float] = field(default_factory=list)
    widths: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class _Region:
    """One contiguous over-threshold run within a single frame's spectrum."""

    center_hz: float
    peak_db: float
    peak_snr_db: float
    width_hz: float


class WavenisWidebandAnalyzer:
    """Extract measured-centroid bursts from consecutive complex IQ blocks."""

    def __init__(
        self,
        *,
        frame_samples: int = 2048,
        welch_segments: int = 4,
        threshold_db: float = 12.0,
        noise_alpha: float = 0.02,
        holdoff_frames: int = 2,
        min_qualified_frames: int = 2,
        association_hz: int = 15_000,
        recent_limit: int = 200,
    ) -> None:
        self.frame_samples = int(frame_samples)
        # Welch-average this many sub-segments per frame. Per-bin detection is
        # much noisier than the old wide-mask average, so a raw periodogram lets
        # noise cross a 12 dB threshold. Averaging K sub-PSDs cuts noise
        # variance ~K-fold while keeping a narrow tone at full height (unlike
        # frequency smoothing, which dilutes spikes) and preserving frame
        # timing (still one PSD per frame).
        self.welch_segments = max(1, int(welch_segments))
        self.threshold_db = float(threshold_db)
        self.noise_alpha = float(noise_alpha)
        self.holdoff_frames = int(holdoff_frames)
        self.min_qualified_frames = int(min_qualified_frames)
        # Two frame-regions closer than this are considered the same emission
        # across frames. Kept well below the ~25-30 kHz spacing seen on air so
        # genuinely distinct narrow tones stay separate tracks.
        self.association_hz = float(association_hz)
        self._states = [_ChannelState() for _ in WAVENIS_CHANNELS_HZ]
        self._tracks: list[_Track] = []
        self._recent: deque[WavenisBurst] = deque(maxlen=recent_limit)
        self._candidates: deque[dict] = deque(maxlen=recent_limit)
        self._candidate_count = 0
        self._bucket_flag_count: dict[int, int] = {}
        self._suppressed_recurring = 0
        self._pending = np.empty(0, dtype=np.complex64)
        self._sample_cursor = 0
        self._sequence = 0
        self._sample_rate = 0
        self._center_hz = 0
        self._frames_processed = 0
        # Per-bin noise floor over the in-band region; sized on first block.
        self._bin_freqs: np.ndarray | None = None
        self._bin_noise_db: np.ndarray | None = None
        self._bin_step = 0.0

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
        self._tracks = []
        self._recent = deque(maxlen=recent_limit)
        # In-memory candidate view is per-session; the all-time durable record
        # lives on disk (see CandidateLog), so zeroing these here is safe.
        self._candidates = deque(maxlen=recent_limit)
        self._candidate_count = 0
        self._bucket_flag_count = {}
        self._suppressed_recurring = 0
        self._pending = np.empty(0, dtype=np.complex64)
        self._sample_cursor = 0
        self._sequence = 0
        self._sample_rate = 0
        self._center_hz = 0
        self._frames_processed = 0
        self._bin_freqs = None
        self._bin_noise_db = None
        self._bin_step = 0.0

    def discontinuity(self, missing_samples: int = 0) -> None:
        """Drop partial bursts when acquisition reports a sample-sequence gap."""
        self._pending = np.empty(0, dtype=np.complex64)
        self._sample_cursor += max(0, int(missing_samples))
        self._tracks = []

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

        # Welch-average K sub-segments per frame into one lower-variance PSD.
        seg = self.frame_samples // self.welch_segments
        sub = frames[:, : seg * self.welch_segments].reshape(frame_count, self.welch_segments, seg)
        window = np.hanning(seg).astype(np.float32)
        spectrum = np.fft.fftshift(np.fft.fft(sub * window, axis=2), axes=2)
        power = np.mean(np.abs(spectrum) ** 2, axis=1)
        offsets = np.fft.fftshift(np.fft.fftfreq(seg, d=1.0 / sample_rate))
        absolute_freqs = offsets + float(center_hz)

        # Restrict all work to the observable grid span (plus guard); bins
        # outside it are irrelevant to the Wavenis question and only add noise.
        in_band = (absolute_freqs >= WAVENIS_CHANNELS_HZ[0] - WAVENIS_GRID_GUARD_HZ) & (
            absolute_freqs <= WAVENIS_CHANNELS_HZ[-1] + WAVENIS_GRID_GUARD_HZ
        )
        band_freqs = absolute_freqs[in_band]
        band_power = power[:, in_band]
        power_db = 10.0 * np.log10(band_power + 1e-20)
        if band_freqs.size > 1:
            self._bin_step = float(band_freqs[1] - band_freqs[0])

        if (
            self._bin_noise_db is None
            or self._bin_freqs is None
            or self._bin_freqs.size != band_freqs.size
        ):
            self._bin_freqs = band_freqs.copy()
            # Seed each bin's floor from a robust within-block percentile so a
            # block that also holds a burst still establishes a sane floor.
            self._bin_noise_db = np.percentile(power_db, 20.0, axis=0)

        emitted: list[WavenisBurst] = []
        for frame_index in range(frame_count):
            frame_start = self._sample_cursor + frame_index * self.frame_samples
            frame_end = frame_start + self.frame_samples
            row_db = power_db[frame_index]
            occupied = row_db >= self._bin_noise_db + self.threshold_db
            regions = self._find_regions(row_db, occupied)
            emitted.extend(self._track_regions(regions, frame_start, frame_end, sample_rate))

            # Adapt only bins that are not currently occupied. Clamp upward
            # movement so repeated impulsive energy cannot redefine the floor.
            quiet = ~occupied
            delta = np.clip(row_db[quiet] - self._bin_noise_db[quiet], -3.0, 0.25)
            self._bin_noise_db[quiet] += self.noise_alpha * delta

        self._sample_cursor += used
        self._frames_processed += frame_count
        return emitted

    def _find_regions(self, row_db: np.ndarray, occupied: np.ndarray) -> list[_Region]:
        """Group contiguous over-threshold bins into measured-centroid regions."""
        assert self._bin_freqs is not None and self._bin_noise_db is not None
        if not occupied.any():
            return []
        # Boundaries of contiguous True runs.
        edges = np.diff(occupied.astype(np.int8))
        starts = np.flatnonzero(edges == 1) + 1
        stops = np.flatnonzero(edges == -1) + 1
        if occupied[0]:
            starts = np.insert(starts, 0, 0)
        if occupied[-1]:
            stops = np.append(stops, occupied.size)

        regions: list[_Region] = []
        for lo, hi in zip(starts, stops, strict=True):
            seg_db = row_db[lo:hi]
            seg_freqs = self._bin_freqs[lo:hi]
            linear = np.power(10.0, seg_db / 10.0)
            centroid = float(np.sum(linear * seg_freqs) / np.sum(linear))
            peak_local = int(np.argmax(seg_db))
            peak_db = float(seg_db[peak_local])
            peak_snr = peak_db - float(self._bin_noise_db[lo + peak_local])
            # Occupied bandwidth = span of bins within OCCUPIED_BW_DB of the
            # peak, NOT every bin above the detection threshold. A strong
            # narrowband tone leaks across many above-threshold bins but its
            # -10 dB skirt is still only a bin or two, so this stays narrow for
            # tones and only reads wide for genuinely wideband (GFSK) energy.
            near_peak = int(np.count_nonzero(seg_db >= peak_db - OCCUPIED_BW_DB))
            width_hz = float(max(1, near_peak)) * self._bin_step
            regions.append(
                _Region(
                    center_hz=centroid,
                    peak_db=peak_db,
                    peak_snr_db=peak_snr,
                    width_hz=width_hz,
                )
            )
        return regions

    def _track_regions(
        self,
        regions: list[_Region],
        frame_start: int,
        frame_end: int,
        sample_rate: int,
    ) -> list[WavenisBurst]:
        """Associate this frame's regions to open tracks; close stale ones."""
        matched: set[int] = set()
        for region in regions:
            track_idx = self._nearest_open_track(region.center_hz, matched)
            if track_idx is None:
                self._tracks.append(
                    _Track(
                        start_sample=frame_start,
                        last_above_end_sample=frame_end,
                        center_hz=region.center_hz,
                        peak_db=region.peak_db,
                        peak_snr_db=region.peak_snr_db,
                        above_frames=1,
                        centroids=[region.center_hz],
                        widths=[region.width_hz],
                    )
                )
                matched.add(len(self._tracks) - 1)
                continue
            track = self._tracks[track_idx]
            track.last_above_end_sample = frame_end
            track.below_frames = 0
            track.above_frames += 1
            track.peak_db = max(track.peak_db, region.peak_db)
            track.peak_snr_db = max(track.peak_snr_db, region.peak_snr_db)
            track.centroids.append(region.center_hz)
            track.widths.append(region.width_hz)
            track.center_hz = float(np.median(track.centroids))
            matched.add(track_idx)

        emitted: list[WavenisBurst] = []
        survivors: list[_Track] = []
        for idx, track in enumerate(self._tracks):
            if idx in matched:
                survivors.append(track)
                continue
            track.below_frames += 1
            if track.below_frames >= self.holdoff_frames:
                emitted.append(self._finish_track(track, sample_rate))
            else:
                survivors.append(track)
        self._tracks = survivors
        return emitted

    def _nearest_open_track(self, center_hz: float, matched: set[int]) -> int | None:
        best_idx: int | None = None
        best_dist = self.association_hz
        for idx, track in enumerate(self._tracks):
            if idx in matched:
                continue
            dist = abs(track.center_hz - center_hz)
            if dist <= best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    def _finish_track(self, track: _Track, sample_rate: int) -> WavenisBurst:
        self._sequence += 1
        duration_samples = max(0, track.last_above_end_sample - track.start_sample)
        duration_ms = duration_samples / sample_rate * 1000.0
        measured_hz = float(np.median(track.centroids))
        channel_index = _nearest_grid_index(measured_hz)
        offset = measured_hz - float(_GRID_HZ[channel_index])
        qualified = track.above_frames >= self.min_qualified_frames
        noise_db = float(self._bin_noise_at(measured_hz))
        # Median (steady-state) width, not max: a short burst's on/off edge
        # frames splatter broadband and would otherwise inflate the bandwidth.
        bandwidth_hz = int(round(float(np.median(track.widths)))) if track.widths else 0
        start_s = track.start_sample / sample_rate

        reasons, score = self._classify(duration_ms=duration_ms, bandwidth_hz=bandwidth_hz)
        is_candidate = False
        if qualified and score >= CANDIDATE_MIN_SCORE:
            # Novelty filter: flag a frequency bucket only a few times, then
            # treat it as a persistent fixture and suppress (but count) repeats.
            bucket = int(round(measured_hz / CANDIDATE_BUCKET_HZ))
            seen = self._bucket_flag_count.get(bucket, 0)
            if seen < CANDIDATE_PERSISTENT_AFTER:
                self._bucket_flag_count[bucket] = seen + 1
                is_candidate = True
            else:
                self._suppressed_recurring += 1

        burst = WavenisBurst(
            sequence=self._sequence,
            channel_index=channel_index,
            freq_hz=int(round(measured_hz)),
            start_s=start_s,
            duration_ms=round(duration_ms, 3),
            bandwidth_hz=bandwidth_hz,
            peak_snr_db=round(track.peak_snr_db, 3),
            noise_db=round(noise_db, 3),
            above_frames=track.above_frames,
            qualified=qualified,
            freq_offset_hz=round(offset, 1),
            candidate_reasons=tuple(reasons),
            candidate_score=round(score, 1),
            is_candidate=is_candidate,
        )
        state = self._states[channel_index]
        state.observations += 1
        state.qualified_observations += int(qualified)
        state.last_seen_s = burst.start_s
        state.peak_snr_db = max(state.peak_snr_db, track.peak_snr_db)
        state.noise_db = noise_db
        self._recent.append(burst)
        if is_candidate:
            self._candidate_count += 1
            self._candidates.append(burst.to_dict())
        return burst

    def _classify(self, *, duration_ms: float, bandwidth_hz: int) -> tuple[list[str], float]:
        """Score a burst against the Wavenis fingerprint; return (reasons, score)."""
        reasons: list[str] = []
        score = 0.0
        if LONG_WAKEUP_MS[0] <= duration_ms <= LONG_WAKEUP_MS[1]:
            reasons.append("long_wakeup")
            score += 3.0
        if SHORT_WAKEUP_MS[0] <= duration_ms <= SHORT_WAKEUP_MS[1]:
            reasons.append("short_wakeup")
            score += 1.0
        if duration_ms >= WIDEBAND_MIN_DURATION_MS and bandwidth_hz >= WIDEBAND_MIN_HZ:
            reasons.append("wideband")
            score += 2.0
        return reasons, score

    def _bin_noise_at(self, freq_hz: float) -> float:
        if self._bin_freqs is None or self._bin_noise_db is None or self._bin_freqs.size == 0:
            return -120.0
        idx = int(np.argmin(np.abs(self._bin_freqs - freq_hz)))
        return float(self._bin_noise_db[idx])

    def snapshot(self) -> dict[str, object]:
        active_indices = {_nearest_grid_index(track.center_hz) for track in self._tracks}
        channels = []
        for index, (freq_hz, state) in enumerate(
            zip(WAVENIS_CHANNELS_HZ, self._states, strict=True)
        ):
            channels.append(
                {
                    "index": index,
                    "freq_hz": freq_hz,
                    "noise_db": round(state.noise_db, 3) if state.noise_db is not None else None,
                    "active": index in active_indices,
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
            "candidates_flagged": self._candidate_count,
            "recent_candidates": list(self._candidates),
            "suppressed_recurring": self._suppressed_recurring,
            "recurring_emitters_hz": sorted(
                bucket * CANDIDATE_BUCKET_HZ
                for bucket, count in self._bucket_flag_count.items()
                if count >= CANDIDATE_PERSISTENT_AFTER
            ),
        }
