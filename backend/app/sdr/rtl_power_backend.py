"""rtl_power subprocess backend (optional sweep source).

Wraps the `rtl_power` CLI to obtain a wideband power sweep. This backend does
NOT provide raw IQ (rtl_power only yields binned power), so `read_iq` raises;
callers that want a swept PSD use `sweep()` instead. Guarded on `shutil.which`.

RECEIVE-ONLY.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

import numpy as np

from .base import SdrBackend, SdrInfo, TuneRange


class RtlPowerUnavailable(RuntimeError):
    """Raised when the rtl_power binary is not on PATH."""


@dataclass(frozen=True)
class SweepResult:
    freqs_hz: np.ndarray
    power_db: np.ndarray


class RtlPowerBackend(SdrBackend):
    """Sweep-only backend using the rtl_power CLI."""

    name = "rtl_power"
    _FREQ_RANGE = (24_000_000, 1_766_000_000)

    def __init__(
        self,
        *,
        device_index: int = 0,
        sample_rate: int = 2_400_000,
        center_hz: int = 868_500_000,
        gain: str | float = "auto",
        ppm: int = 0,
        bin_hz: int = 10_000,
        integration_s: float = 1.0,
        binary: str = "rtl_power",
    ) -> None:
        self._device_index = int(device_index)
        self._sample_rate = int(sample_rate)
        self._center_hz = int(center_hz)
        self._gain = gain
        self._ppm = int(ppm)
        self._bin_hz = int(bin_hz)
        self._integration_s = float(integration_s)
        self._binary = binary
        self._path = shutil.which(binary)

    @property
    def available(self) -> bool:
        return self._path is not None

    def open(self) -> None:
        if self._path is None:
            raise RtlPowerUnavailable(
                f"'{self._binary}' not found on PATH. Install rtl-sdr tools or use SDR_BACKEND=sim."
            )

    def close(self) -> None:
        return None

    def read_iq(self, n: int) -> np.ndarray:
        raise NotImplementedError(
            "rtl_power backend does not expose raw IQ; use sweep() for binned PSD."
        )

    def sweep(self, start_hz: int, end_hz: int) -> SweepResult:  # pragma: no cover - CLI
        """Run one rtl_power integration over [start_hz, end_hz]."""
        if self._path is None:
            raise RtlPowerUnavailable(f"'{self._binary}' not found on PATH.")
        gain_arg = (
            "0" if (isinstance(self._gain, str) and self._gain == "auto") else str(self._gain)
        )
        cmd = [
            self._path,
            "-f",
            f"{start_hz}:{end_hz}:{self._bin_hz}",
            "-i",
            f"{self._integration_s:g}",
            "-1",  # single shot
            "-d",
            str(self._device_index),
            "-p",
            str(self._ppm),
            "-g",
            gain_arg,
            "-",  # stdout
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
        return self._parse_csv(proc.stdout)

    @staticmethod
    def _parse_csv(text: str) -> SweepResult:  # pragma: no cover - CLI
        freqs: list[float] = []
        powers: list[float] = []
        for line in text.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 7:
                continue
            try:
                f_low = float(parts[2])
                f_step = float(parts[4])
                vals = [float(v) for v in parts[6:]]
            except ValueError:
                continue
            for i, v in enumerate(vals):
                freqs.append(f_low + i * f_step)
                powers.append(v)
        return SweepResult(
            freqs_hz=np.asarray(freqs, dtype=np.float64),
            power_db=np.asarray(powers, dtype=np.float64),
        )

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
            backend="rtl_power",
            name="rtl_power sweep",
            index=self._device_index,
            available=self.available,
            simulation=False,
            tuner="rtl_power",
            gains=[0.0, 15.7, 28.0, 42.1, 49.6],
            sample_rates=[self._sample_rate],
            freq_range_hz=self._FREQ_RANGE,
        )
