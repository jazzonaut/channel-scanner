"""SDR backend factory with automatic fallback to simulation.

Selects a backend from settings. If the requested hardware backend cannot be
constructed/opened, it logs the reason and transparently falls back to the
simulator so the app is always runnable. RECEIVE-ONLY.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ..config import Settings
from .base import SdrBackend
from .rtl_power_backend import RtlPowerBackend, RtlPowerUnavailable
from .rtlsdr_backend import RtlSdrBackend, RtlSdrUnavailable
from .sim import SimulatedSdr

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BackendSelection:
    """The backend the factory actually produced, and how it got there.

    ``degraded`` is the load-bearing field: it is True only when the operator
    explicitly asked for real hardware (``SIMULATION_MODE=false`` and a non-sim
    backend) but the factory had to fall back to the simulator. That is the case
    callers must surface loudly -- a silent sim fallback can otherwise masquerade
    as a real capture for days (see the ppm/open failure that motivated this).
    """

    backend: SdrBackend
    requested: str
    degraded: bool = False
    reason: str | None = None


def _build_sim(settings: Settings) -> SimulatedSdr:
    center = (settings.scan_start_hz + settings.scan_end_hz) // 2
    return SimulatedSdr(
        sample_rate=settings.sdr_sample_rate,
        center_hz=center,
        gain=settings.gain_value(),
        ppm=settings.sdr_ppm,
    )


def _fallback(settings: Settings, requested: str, reason: str) -> BackendSelection:
    """Fall back to the simulator, flagging it as degraded when HW was demanded."""
    # We only reach the fallback branches when simulation was NOT requested, so
    # a fallback here always means hardware was wanted but unavailable.
    degraded = not settings.simulation_mode
    log.warning("sdr.backend.fallback", requested=requested, error=reason, degraded=degraded)
    return BackendSelection(
        backend=_build_sim(settings),
        requested=requested,
        degraded=degraded,
        reason=reason,
    )


def create_backend(settings: Settings) -> BackendSelection:
    """Select the configured backend, falling back to sim on any failure.

    Always returns a usable backend so the app stays runnable, but reports via
    ``BackendSelection.degraded`` whether an explicit hardware request silently
    became simulation, so the caller can fail health checks and alert.
    """
    backend = settings.sdr_backend
    center = (settings.scan_start_hz + settings.scan_end_hz) // 2

    if settings.simulation_mode or backend == "sim":
        log.info("sdr.backend.selected", backend="sim", reason="simulation_mode_or_sim")
        return BackendSelection(backend=_build_sim(settings), requested="sim")

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
            return BackendSelection(backend=dev, requested="rtlsdr")
        except (RtlSdrUnavailable, Exception) as exc:  # noqa: BLE001
            return _fallback(settings, "rtlsdr", str(exc))

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
            return BackendSelection(backend=dev_rp, requested="rtl_power")
        return _fallback(settings, "rtl_power", "rtl_power binary not found")

    if backend == "soapy":
        # SoapySDR is not bundled; fall back cleanly (extensible hook point).
        return _fallback(settings, "soapy", "soapy not implemented")

    return _fallback(settings, backend, "unknown backend")


__all__ = [
    "create_backend",
    "BackendSelection",
    "RtlSdrUnavailable",
    "RtlPowerUnavailable",
]
