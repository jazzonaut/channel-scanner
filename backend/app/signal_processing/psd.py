"""Power spectral density estimation from complex IQ samples.

Uses Welch's method (scipy.signal.welch) to produce a stable PSD in dB, with
frequency bins mapped to absolute RF Hz given a center frequency and sample
rate. Everything here is a pure function operating on numpy arrays.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal


@dataclass(frozen=True)
class PsdResult:
    """A single PSD estimate.

    Attributes:
        freqs_hz: Absolute RF frequency of each bin (Hz), ascending.
        power_db: Power per bin in dB (10*log10 of PSD magnitude).
    """

    freqs_hz: np.ndarray  # float64, shape (n,)
    power_db: np.ndarray  # float64, shape (n,)

    @property
    def bin_count(self) -> int:
        return int(self.freqs_hz.shape[0])

    @property
    def bin_width_hz(self) -> float:
        if self.freqs_hz.shape[0] < 2:
            return 0.0
        return float(self.freqs_hz[1] - self.freqs_hz[0])


def compute_psd(
    iq: np.ndarray,
    *,
    center_hz: float,
    sample_rate: float,
    fft_size: int = 2048,
    window: str = "hann",
) -> PsdResult:
    """Compute a Welch PSD for complex baseband IQ.

    Args:
        iq: complex64/complex128 baseband samples.
        center_hz: RF center frequency the samples were tuned to.
        sample_rate: sample rate in Hz.
        fft_size: FFT / segment length (nperseg).
        window: scipy window name.

    Returns:
        PsdResult with fftshifted (ascending) absolute frequencies and dB power.
    """
    if iq.size == 0:
        freqs = np.array([center_hz], dtype=np.float64)
        return PsdResult(freqs_hz=freqs, power_db=np.array([-120.0], dtype=np.float64))

    nperseg = int(min(fft_size, iq.size))
    if nperseg < 8:
        nperseg = int(iq.size)

    freqs, psd = signal.welch(
        iq,
        fs=sample_rate,
        window=window,
        nperseg=nperseg,
        noverlap=nperseg // 2,
        return_onesided=False,  # complex input -> two-sided spectrum
        detrend=False,
        scaling="density",
    )

    # welch with two-sided returns freqs in FFT order; shift to ascending.
    order = np.argsort(freqs)
    freqs = freqs[order]
    psd = psd[order]

    abs_freqs = center_hz + freqs
    # Guard against log10(0).
    psd = np.maximum(psd, 1e-20)
    power_db = 10.0 * np.log10(psd)
    return PsdResult(freqs_hz=abs_freqs.astype(np.float64), power_db=power_db.astype(np.float64))


def reduce_bins(power_db: np.ndarray, target_bins: int) -> np.ndarray:
    """Downsample a power spectrum to `target_bins` using max-pooling.

    Max-pooling (rather than mean) preserves narrowband peaks that matter for
    display. Returns the input unchanged if it already fits.
    """
    n = power_db.shape[0]
    if target_bins <= 0 or n <= target_bins:
        return power_db.astype(np.float32)
    # Split into target_bins groups; take max of each. Handle non-divisible n.
    idx = np.linspace(0, n, target_bins + 1).astype(int)
    out = np.empty(target_bins, dtype=np.float32)
    for i in range(target_bins):
        lo, hi = idx[i], max(idx[i] + 1, idx[i + 1])
        out[i] = float(np.max(power_db[lo:hi]))
    return out


def resample_freq_axis(freqs_hz: np.ndarray, target_bins: int) -> np.ndarray:
    """Linear frequency axis matching `reduce_bins` output length."""
    n = freqs_hz.shape[0]
    if target_bins <= 0 or n <= target_bins:
        return freqs_hz.astype(np.float64)
    return np.linspace(freqs_hz[0], freqs_hz[-1], target_bins, dtype=np.float64)
