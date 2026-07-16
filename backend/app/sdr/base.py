"""SDR backend abstract base class.

All backends are RECEIVE-ONLY. The interface only permits configuring the
receiver and reading complex IQ samples. No method transmits.
"""

from __future__ import annotations

import abc
import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TuneRange:
    """Inclusive frequency tuning range in Hz."""

    min_hz: int
    max_hz: int

    def contains(self, hz: int) -> bool:
        return self.min_hz <= hz <= self.max_hz


@dataclass(frozen=True)
class SdrInfo:
    """Static/dynamic capability descriptor for a backend."""

    backend: str
    name: str
    index: int
    available: bool
    simulation: bool
    tuner: str
    gains: list[float]
    sample_rates: list[int]
    freq_range_hz: tuple[int, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "name": self.name,
            "index": self.index,
            "available": self.available,
            "simulation": self.simulation,
            "tuner": self.tuner,
            "gains": self.gains,
            "sample_rates": self.sample_rates,
            "freq_range_hz": [self.freq_range_hz[0], self.freq_range_hz[1]],
        }


class SdrBackend(abc.ABC):
    """Abstract receive-only SDR backend.

    Concrete backends must be usable from a worker thread. `read_iq` MUST NOT be
    called from the asyncio event loop directly -- callers use run_in_executor.
    """

    #: Human-readable backend identifier (e.g. "sim", "rtlsdr").
    name: str = "base"

    @abc.abstractmethod
    def open(self) -> None:
        """Open/initialise the device. Idempotent."""

    @abc.abstractmethod
    def close(self) -> None:
        """Release the device. Idempotent."""

    @abc.abstractmethod
    def read_iq(self, n: int) -> np.ndarray:
        """Read `n` complex64 baseband samples. Blocking; call off-loop."""

    @abc.abstractmethod
    def set_center_freq(self, hz: int) -> None:
        """Tune the receiver center frequency (Hz)."""

    @abc.abstractmethod
    def set_sample_rate(self, sps: int) -> None:
        """Set the sample rate (samples/sec)."""

    @abc.abstractmethod
    def set_gain(self, gain: str | float) -> None:
        """Set gain: 'auto' or a float dB value."""

    @abc.abstractmethod
    def set_ppm(self, ppm: int) -> None:
        """Set the frequency-correction in parts-per-million."""

    @abc.abstractmethod
    def get_info(self) -> SdrInfo:
        """Return a capability descriptor."""

    # --- Concrete helpers shared by all backends ---

    @property
    @abc.abstractmethod
    def tune_range(self) -> TuneRange:
        """Supported tuning range."""

    @property
    def center_freq(self) -> int:
        return getattr(self, "_center_hz", 0)

    @property
    def sample_rate(self) -> int:
        return getattr(self, "_sample_rate", 0)

    def supports_bandwidth(self, bw_hz: int) -> bool:
        """Whether a requested capture bandwidth fits within the sample rate."""
        return 0 < bw_hz <= self.sample_rate

    def stream_iq(
        self,
        n: int,
        callback: Callable[[np.ndarray], None],
        stop_event: threading.Event,
    ) -> None:
        """Continuously deliver IQ blocks until ``stop_event`` is set.

        The generic implementation preserves one owner for backend reads. Real
        backends may override this with a device-native asynchronous stream.
        This method is blocking and must run in its own worker thread.
        """
        while not stop_event.is_set():
            callback(self.read_iq(n))

    def cancel_stream(self) -> None:
        """Interrupt a device-native stream, if the backend has one."""
        return None

    def __enter__(self) -> SdrBackend:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
