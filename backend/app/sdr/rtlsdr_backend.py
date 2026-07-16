"""Real RTL-SDR backend via pyrtlsdr (optional dependency).

The `rtlsdr` import is guarded: if pyrtlsdr (and its librtlsdr) is not present,
constructing this backend raises a clear, actionable error so the factory can
fall back to simulation. RECEIVE-ONLY: only tuning + sample capture.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np

from .base import SdrBackend, SdrInfo, TuneRange

try:  # pragma: no cover - depends on optional native lib
    from rtlsdr import RtlSdr  # type: ignore

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # noqa: BLE001 - want any import failure captured
    RtlSdr = None  # type: ignore
    _IMPORT_ERROR = exc


class RtlSdrUnavailable(RuntimeError):
    """Raised when the RTL-SDR hardware/library cannot be used."""


class RtlSdrBackend(SdrBackend):
    """Thin wrapper over pyrtlsdr. Receive-only."""

    name = "rtlsdr"
    _FREQ_RANGE = (24_000_000, 1_766_000_000)

    def __init__(
        self,
        *,
        device_index: int = 0,
        sample_rate: int = 2_400_000,
        center_hz: int = 868_500_000,
        gain: str | float = "auto",
        ppm: int = 0,
    ) -> None:
        if RtlSdr is None:
            raise RtlSdrUnavailable(
                "pyrtlsdr is not installed or librtlsdr is missing. "
                "Install the optional extra with `pip install '.[rtlsdr]'` and "
                f"ensure librtlsdr is present. Original import error: {_IMPORT_ERROR!r}"
            )
        self._device_index = int(device_index)
        self._sample_rate = int(sample_rate)
        self._center_hz = int(center_hz)
        self._gain = gain
        self._ppm = int(ppm)
        self._dev: RtlSdr | None = None  # type: ignore[valid-type]
        self._applied_center_hz: int | None = None
        self._applied_sample_rate: int | None = None

    def open(self) -> None:
        if self._dev is not None:
            return
        try:  # pragma: no cover - requires hardware
            self._dev = RtlSdr(device_index=self._device_index)
        except Exception as exc:  # noqa: BLE001
            raise RtlSdrUnavailable(
                f"Failed to open RTL-SDR device index {self._device_index}: {exc}"
            ) from exc
        self.set_sample_rate(self._sample_rate)
        self.set_center_freq(self._center_hz)
        self.set_gain(self._gain)
        self.set_ppm(self._ppm)

    def close(self) -> None:  # pragma: no cover - requires hardware
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None
                self._applied_center_hz = None
                self._applied_sample_rate = None

    def _require(self) -> RtlSdr:  # type: ignore[valid-type]
        if self._dev is None:
            raise RtlSdrUnavailable("Device not open; call open() first.")
        return self._dev

    def read_iq(self, n: int) -> np.ndarray:  # pragma: no cover - requires hardware
        dev = self._require()
        samples = dev.read_samples(int(n))
        return np.asarray(samples, dtype=np.complex64)

    def stream_iq(
        self,
        n: int,
        callback: Callable[[np.ndarray], None],
        stop_event: threading.Event,
    ) -> None:  # pragma: no cover - requires hardware
        """Use librtlsdr's continuous async transfer rather than repeated reads."""
        dev = self._require()

        def on_samples(samples: np.ndarray, _context: object = None) -> None:
            if stop_event.is_set():
                dev.cancel_read_async()
                return
            callback(np.asarray(samples, dtype=np.complex64))

        dev.read_samples_async(on_samples, num_samples=int(n))

    def cancel_stream(self) -> None:  # pragma: no cover - requires hardware
        if self._dev is not None:
            self._dev.cancel_read_async()

    def set_center_freq(self, hz: int) -> None:
        hz = int(hz)
        self._center_hz = hz
        if self._dev is not None and hz != self._applied_center_hz:  # pragma: no cover
            self._dev.center_freq = hz
            self._applied_center_hz = hz

    def set_sample_rate(self, sps: int) -> None:
        sps = int(sps)
        self._sample_rate = sps
        if self._dev is not None and sps != self._applied_sample_rate:  # pragma: no cover
            self._dev.sample_rate = sps
            self._applied_sample_rate = sps

    def set_gain(self, gain: str | float) -> None:
        self._gain = gain
        if self._dev is not None:  # pragma: no cover
            if isinstance(gain, str) and gain.lower() == "auto":
                self._dev.gain = "auto"
            else:
                self._dev.gain = float(gain)

    def set_ppm(self, ppm: int) -> None:
        self._ppm = int(ppm)
        if self._dev is not None:  # pragma: no cover
            self._dev.freq_correction = int(ppm)

    @property
    def tune_range(self) -> TuneRange:
        return TuneRange(self._FREQ_RANGE[0], self._FREQ_RANGE[1])

    def get_info(self) -> SdrInfo:  # pragma: no cover - requires hardware
        gains: list[float] = []
        tuner = "unknown"
        if self._dev is not None:
            try:
                gains = [float(g) / 10.0 for g in self._dev.get_gains()]
            except Exception:  # noqa: BLE001
                gains = []
            tuner = getattr(self._dev, "get_tuner_type", lambda: "unknown")()
        return SdrInfo(
            backend="rtlsdr",
            name=f"RTL-SDR #{self._device_index}",
            index=self._device_index,
            available=self._dev is not None,
            simulation=False,
            tuner=str(tuner),
            gains=gains or [0.0, 15.7, 28.0, 42.1, 49.6],
            sample_rates=[250_000, 1_024_000, 2_048_000, 2_400_000, 3_200_000],
            freq_range_hz=self._FREQ_RANGE,
        )
