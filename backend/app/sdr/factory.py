"""SDR backend factory with automatic fallback to simulation.

Selects a backend from settings. If the requested hardware backend cannot be
constructed/opened, it logs the reason and transparently falls back to the
simulator so the app is always runnable. RECEIVE-ONLY.
"""

from __future__ import annotations

import structlog

from ..config import Settings
from .base import SdrBackend
from .rtl_power_backend import RtlPowerBackend, RtlPowerUnavailable
from .rtlsdr_backend import RtlSdrBackend, RtlSdrUnavailable
from .sim import SimulatedSdr

log = structlog.get_logger(__name__)


def _build_sim(settings: Settings) -> SimulatedSdr:
    center = (settings.scan_start_hz + settings.scan_end_hz) // 2
    return SimulatedSdr(
        sample_rate=settings.sdr_sample_rate,
        center_hz=center,
        gain=settings.gain_value(),
        ppm=settings.sdr_ppm,
    )


def create_backend(settings: Settings) -> SdrBackend:
    """Create the configured backend, falling back to sim on any failure."""
    backend = settings.sdr_backend
    center = (settings.scan_start_hz + settings.scan_end_hz) // 2

    if settings.simulation_mode or backend == "sim":
        log.info("sdr.backend.selected", backend="sim", reason="simulation_mode_or_sim")
        return _build_sim(settings)

    if backend == "rtlsdr":
        try:
            dev = RtlSdrBackend(
                device_index=settings.sdr_device_index,
                sample_rate=settings.sdr_sample_rate,
                center_hz=center,
                gain=settings.gain_value(),
                ppm=settings.sdr_ppm,
            )
            dev.open()
            log.info("sdr.backend.selected", backend="rtlsdr", available=True)
            return dev
        except (RtlSdrUnavailable, Exception) as exc:  # noqa: BLE001
            log.warning("sdr.backend.fallback", requested="rtlsdr", error=str(exc))
            return _build_sim(settings)

    if backend == "rtl_power":
        dev_rp = RtlPowerBackend(
            device_index=settings.sdr_device_index,
            sample_rate=settings.sdr_sample_rate,
            center_hz=center,
            gain=settings.gain_value(),
            ppm=settings.sdr_ppm,
        )
        if dev_rp.available:
            log.info("sdr.backend.selected", backend="rtl_power", available=True)
            return dev_rp
        log.warning(
            "sdr.backend.fallback",
            requested="rtl_power",
            error="rtl_power binary not found",
        )
        return _build_sim(settings)

    if backend == "soapy":
        # SoapySDR is not bundled; fall back cleanly (extensible hook point).
        log.warning("sdr.backend.fallback", requested="soapy", error="soapy not implemented")
        return _build_sim(settings)

    log.warning("sdr.backend.fallback", requested=backend, error="unknown backend")
    return _build_sim(settings)


__all__ = [
    "create_backend",
    "RtlSdrUnavailable",
    "RtlPowerUnavailable",
]
