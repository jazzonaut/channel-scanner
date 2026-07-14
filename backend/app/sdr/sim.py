"""Simulated SDR backend.

Generates realistic complex baseband IQ with:
  * a configurable Gaussian noise floor,
  * several intermittent narrowband emitters,
  * at least one repeating "meter-like" burst (~every few seconds),
  * slow frequency drift,
  * time-varying SNR,
  * occasional wideband interference.

The realization is deterministic given a seed and the elapsed sample clock, yet
time-varying (bursts turn on/off) so the detector, clusterer and recurrence
estimator all have something to find. Emitters are defined in ABSOLUTE RF Hz;
only those falling within the current tuned window appear in the IQ.

RECEIVE-ONLY: this only synthesises what a receiver would observe.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .base import SdrBackend, SdrInfo, TuneRange


@dataclass
class SimEmitter:
    """A synthetic emitter defined in absolute RF frequency."""

    freq_hz: float
    bandwidth_hz: float
    snr_db: float
    period_s: float  # on/off cycle length
    duty: float  # fraction of the period the emitter is active
    phase_s: float = 0.0  # time offset of the cycle
    drift_hz: float = 0.0  # peak slow frequency drift
    label: str = ""

    def active(self, t: float) -> bool:
        cycle = (t + self.phase_s) % self.period_s
        return cycle < self.duty * self.period_s

    def current_freq(self, t: float) -> float:
        if self.drift_hz == 0.0:
            return self.freq_hz
        return self.freq_hz + self.drift_hz * np.sin(2.0 * np.pi * t / 37.0)


# Default synthetic scene inside the 867-870 MHz ISM-ish band.
_DEFAULT_EMITTERS: list[SimEmitter] = [
    # Repeating meter-like short burst every ~4 s (the "meter" pattern).
    SimEmitter(867_500_000, 30_000, 22.0, period_s=4.0, duty=0.06, drift_hz=800.0, label="meter-a"),
    # A second meter on a different cadence.
    SimEmitter(
        869_250_000,
        25_000,
        18.0,
        period_s=6.5,
        duty=0.05,
        phase_s=1.3,
        drift_hz=500.0,
        label="meter-b",
    ),
    # Chatty intermittent narrowband sensor.
    SimEmitter(868_100_000, 40_000, 15.0, period_s=2.3, duty=0.35, phase_s=0.4, label="sensor-1"),
    # Nearly-continuous beacon with mild SNR variation.
    SimEmitter(868_650_000, 20_000, 12.0, period_s=11.0, duty=0.85, drift_hz=300.0, label="beacon"),
    # Slow, wide occasional emitter.
    SimEmitter(867_950_000, 120_000, 9.0, period_s=17.0, duty=0.12, phase_s=5.0, label="wide-slow"),
]


class SimulatedSdr(SdrBackend):
    """Deterministic-yet-time-varying synthetic IQ source."""

    name = "sim"

    _TUNER = "SIM-Tuner"
    _GAINS = [0.0, 9.0, 14.0, 20.0, 27.0, 32.9, 40.2, 49.6]
    _SAMPLE_RATES = [250_000, 1_024_000, 2_048_000, 2_400_000, 3_200_000]
    _FREQ_RANGE = (24_000_000, 1_766_000_000)

    def __init__(
        self,
        *,
        sample_rate: int = 2_400_000,
        center_hz: int = 868_500_000,
        gain: str | float = "auto",
        ppm: int = 0,
        seed: int = 1234,
        noise_floor_db: float = -60.0,
        emitters: list[SimEmitter] | None = None,
    ) -> None:
        self._sample_rate = int(sample_rate)
        self._center_hz = int(center_hz)
        self._gain = gain
        self._ppm = int(ppm)
        self._seed = int(seed)
        self._noise_floor_db = float(noise_floor_db)
        self._emitters = list(emitters if emitters is not None else _DEFAULT_EMITTERS)
        self._rng = np.random.default_rng(seed)
        self._samples_read = 0
        self._opened = False

    # --- lifecycle ---
    def open(self) -> None:
        self._opened = True
        self._samples_read = 0
        self._rng = np.random.default_rng(self._seed)

    def close(self) -> None:
        self._opened = False

    # --- tuning ---
    def set_center_freq(self, hz: int) -> None:
        self._center_hz = int(hz)

    def set_sample_rate(self, sps: int) -> None:
        self._sample_rate = int(sps)

    def set_gain(self, gain: str | float) -> None:
        self._gain = gain

    def set_ppm(self, ppm: int) -> None:
        self._ppm = int(ppm)

    @property
    def tune_range(self) -> TuneRange:
        return TuneRange(self._FREQ_RANGE[0], self._FREQ_RANGE[1])

    def get_info(self) -> SdrInfo:
        return SdrInfo(
            backend="sim",
            name="Simulated RTL-SDR",
            index=0,
            available=True,
            simulation=True,
            tuner=self._TUNER,
            gains=list(self._GAINS),
            sample_rates=list(self._SAMPLE_RATES),
            freq_range_hz=self._FREQ_RANGE,
        )

    # --- IQ synthesis ---
    def read_iq(self, n: int) -> np.ndarray:
        if not self._opened:
            self.open()
        n = int(n)
        fs = float(self._sample_rate)
        t0 = self._samples_read / fs
        # Continuous per-sample time axis for this block.
        t = t0 + np.arange(n, dtype=np.float64) / fs
        block_time = t0  # representative time for on/off decisions

        # Noise floor: complex Gaussian. noise_floor_db sets the linear amplitude.
        noise_amp = 10.0 ** (self._noise_floor_db / 20.0)
        iq = (self._rng.standard_normal(n) + 1j * self._rng.standard_normal(n)).astype(
            np.complex128
        ) * (noise_amp / np.sqrt(2.0))

        half_bw = fs / 2.0
        low = self._center_hz - half_bw
        high = self._center_hz + half_bw

        # Add each active in-band emitter.
        for em in self._emitters:
            f_abs = em.current_freq(block_time)
            if not (low <= f_abs <= high):
                continue
            if not em.active(block_time):
                continue
            # SNR varies slowly with time.
            snr_var = 3.0 * np.sin(2.0 * np.pi * (block_time + em.phase_s) / 5.0)
            snr = em.snr_db + snr_var
            amp = noise_amp * (10.0 ** (snr / 20.0))
            f_base = f_abs - self._center_hz  # baseband offset

            # Narrowband but not a pure tone: sum a few closely spaced tones
            # spread over the emitter bandwidth to give it width.
            n_tones = 5
            offsets = np.linspace(-em.bandwidth_hz / 2.0, em.bandwidth_hz / 2.0, n_tones)
            phases = self._rng.uniform(0, 2 * np.pi, n_tones)
            comp = np.zeros(n, dtype=np.complex128)
            for off, ph in zip(offsets, phases, strict=False):
                comp += np.exp(1j * (2.0 * np.pi * (f_base + off) * t + ph))
            comp /= n_tones
            # Gentle amplitude modulation makes an envelope for fingerprinting.
            env = 0.7 + 0.3 * np.sin(2.0 * np.pi * (t - t0) * 40.0)
            iq += amp * comp * env

        # Occasional wideband interference burst (deterministic via time hash).
        if self._interference_active(block_time):
            chirp_rate = fs / 4.0
            interf = (
                0.4
                * noise_amp
                * np.exp(
                    1j * 2.0 * np.pi * (0.2 * fs * (t - t0) + 0.5 * chirp_rate * (t - t0) ** 2)
                )
            )
            iq += interf

        self._samples_read += n
        return iq.astype(np.complex64)

    @staticmethod
    def _interference_active(t: float) -> bool:
        # Fires for ~0.3 s roughly every 13 s.
        return (t % 13.0) < 0.3
