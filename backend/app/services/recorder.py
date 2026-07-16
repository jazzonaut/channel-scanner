"""Optional IQ recorder (disabled by default).

Captures short baseband IQ segments to SigMF-style files: a `.sigmf-data` blob
of interleaved complex float32 (little-endian) plus a `.sigmf-meta` JSON
sidecar with center freq, sample rate, gain, timestamp and format. Enforces a
maximum single-capture duration and a total storage cap with circular
retention (oldest recordings deleted to make room).

RECEIVE-ONLY: this stores received samples for later local analysis. It never
retransmits. Recording is OFF unless ENABLE_IQ_RECORDING=true.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import structlog

from ..config import Settings
from ..sdr.base import SdrBackend
from ..utils import iso_now

log = structlog.get_logger(__name__)

_SIGMF_DATATYPE = "cf32_le"  # interleaved complex float32, little-endian
_MAX_CAPTURE_MS = 10_000  # hard cap per capture


@dataclass
class RecordingResult:
    path: str
    center_hz: int
    sample_rate: int
    gain: str
    duration_ms: int
    format: str
    bytes: int
    timestamp: str
    sigmf_meta: dict


class Recorder:
    """Writes SigMF-style IQ captures under the recordings dir."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._dir = settings.recordings_dir()
        self._max_bytes = int(settings.max_iq_storage_gb * (1024**3))
        self._enabled = settings.enable_iq_recording

    def apply_config(self, enabled: bool, max_storage_gb: float) -> None:
        """Update recording governance at runtime (from a config change)."""
        self._enabled = bool(enabled)
        self._max_bytes = int(max(0.0, max_storage_gb) * (1024**3))

    def delete_all(self) -> int:
        """Delete every recording file on disk. Returns the number removed."""
        if not self._dir.exists():
            return 0
        count = 0
        for f in self._dir.glob("*.sigmf-*"):
            if f.is_file():
                f.unlink(missing_ok=True)
                count += 1
        return count

    @property
    def enabled(self) -> bool:
        return self._enabled

    def current_bytes(self) -> int:
        if not self._dir.exists():
            return 0
        return sum(f.stat().st_size for f in self._dir.glob("*.sigmf-*") if f.is_file())

    def _enforce_storage_cap(self, incoming_bytes: int) -> None:
        """Delete oldest captures until incoming fits under the cap."""
        if not self._dir.exists():
            return
        data_files = sorted(self._dir.glob("*.sigmf-data"), key=lambda f: f.stat().st_mtime)
        total = self.current_bytes()
        for data in data_files:
            if total + incoming_bytes <= self._max_bytes:
                break
            meta = data.with_suffix(".sigmf-meta")
            freed = data.stat().st_size + (meta.stat().st_size if meta.exists() else 0)
            data.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
            total -= freed
            log.info("recorder.retention.evicted", file=str(data), freed=freed)

    def capture(
        self,
        backend: SdrBackend,
        *,
        center_hz: int,
        duration_ms: int,
        sample_rate: int | None = None,
        gain: str = "auto",
        reason: str = "manual",
        fmt: str = "cf32",
    ) -> RecordingResult:
        """Synchronously capture IQ. Call via run_in_executor (blocking).

        fmt: "cf32" (SigMF cf32_le, full precision) or "cu8" (complex uint8, the
        native RTL-SDR format — 4x smaller, matches triq/rtl_433 tooling).
        """
        if not self._enabled:
            raise RuntimeError("IQ recording is disabled. Set ENABLE_IQ_RECORDING=true to enable.")
        fmt = (fmt or "cf32").lower()
        if fmt not in ("cf32", "cu8"):
            raise ValueError("format must be 'cf32' or 'cu8'")
        # Max-duration guard so a single manual capture can't be unbounded.
        duration_ms = int(min(max(1, duration_ms), _MAX_CAPTURE_MS))
        sr = int(sample_rate or backend.sample_rate or self._settings.sdr_sample_rate)
        n_samples = int(sr * duration_ms / 1000.0)
        n_samples = max(1, n_samples)

        backend.set_center_freq(center_hz)
        backend.set_sample_rate(sr)
        iq = backend.read_iq(n_samples).astype(np.complex64)

        return self.capture_iq(
            iq,
            center_hz=center_hz,
            sample_rate=sr,
            gain=gain,
            reason=reason,
            fmt=fmt,
        )

    def capture_iq(
        self,
        iq: np.ndarray,
        *,
        center_hz: int,
        sample_rate: int,
        gain: str = "auto",
        reason: str = "triggered",
        fmt: str = "cu8",
        annotations: list[dict] | None = None,
    ) -> RecordingResult:
        """Persist IQ that has already passed through the single-owner reader."""
        if not self._enabled:
            raise RuntimeError("IQ recording is disabled. Set ENABLE_IQ_RECORDING=true to enable.")
        fmt = (fmt or "cu8").lower()
        if fmt not in ("cf32", "cu8"):
            raise ValueError("format must be 'cf32' or 'cu8'")
        samples = np.asarray(iq, dtype=np.complex64)
        sr = int(sample_rate)
        max_samples = max(1, int(sr * _MAX_CAPTURE_MS / 1000.0))
        samples = samples[:max_samples]
        bytes_per_sample = 2 if fmt == "cu8" else 8
        self._enforce_storage_cap(int(samples.size) * bytes_per_sample)
        self._dir.mkdir(parents=True, exist_ok=True)

        ts = iso_now()
        stem = f"iq_{center_hz}_{ts.replace(':', '').replace('.', '')}"
        data_path = self._dir / f"{stem}.sigmf-data"
        meta_path = self._dir / f"{stem}.sigmf-meta"

        if fmt == "cu8":
            datatype = "cu8"
            inter_u8 = np.empty(samples.size * 2, dtype=np.uint8)
            inter_u8[0::2] = np.clip(np.round(samples.real * 127.5 + 127.5), 0, 255).astype(
                np.uint8
            )
            inter_u8[1::2] = np.clip(np.round(samples.imag * 127.5 + 127.5), 0, 255).astype(
                np.uint8
            )
            inter_u8.tofile(str(data_path))
        else:
            datatype = _SIGMF_DATATYPE
            interleaved = np.empty(samples.size * 2, dtype=np.float32)
            interleaved[0::2] = samples.real
            interleaved[1::2] = samples.imag
            interleaved.tofile(str(data_path))
        nbytes = data_path.stat().st_size

        meta = {
            "global": {
                "core:datatype": datatype,
                "core:sample_rate": sr,
                "core:version": "1.0.0",
                "core:description": f"receive-only capture ({reason})",
                "core:recorder": "rtl-sdr-channel-detector",
            },
            "captures": [
                {
                    "core:sample_start": 0,
                    "core:frequency": center_hz,
                    "core:datetime": ts,
                    "channel_detector:gain": gain,
                }
            ],
            "annotations": annotations or [],
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        log.info(
            "recorder.captured",
            path=str(data_path),
            center_hz=center_hz,
            sample_rate=sr,
            duration_ms=round(samples.size / sr * 1000.0),
            bytes=nbytes,
            reason=reason,
        )
        return RecordingResult(
            path=str(data_path),
            center_hz=center_hz,
            sample_rate=sr,
            gain=str(gain),
            duration_ms=round(samples.size / sr * 1000.0),
            format=datatype,
            bytes=nbytes,
            timestamp=ts,
            sigmf_meta=meta,
        )

    def delete_files(self, data_path: str) -> None:
        p = Path(data_path)
        p.unlink(missing_ok=True)
        p.with_suffix(".sigmf-meta").unlink(missing_ok=True)
