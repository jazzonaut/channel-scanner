"""Pydantic v2 schemas. Field names are FIXED by CONTRACT.md.

Frequencies are exact integer Hz. Timestamps are ISO-8601 strings with a
trailing Z (UTC). A "candidate channel" is an *inferred* occupied region of
spectrum, never an official/licensed protocol channel.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ChannelStatus = Literal["active", "recently_active", "inactive"]


class Fingerprint(BaseModel):
    center_hz: int
    bandwidth_hz: int
    duration_ms: float
    rel_strength_db: float
    repetition_interval_s: float | None = None
    envelope: list[float] = Field(default_factory=list)


class ScanConfig(BaseModel):
    """Full scan configuration returned by GET /api/config."""

    start_hz: int
    end_hz: int
    step_hz: int
    sample_rate: int
    gain: str
    ppm: int
    dwell_ms: int
    threshold_db: float
    noise_floor_alpha: float
    exclusions: list[tuple[int, int]] = Field(default_factory=list)
    known_channel_widths_hz: list[int] = Field(default_factory=list)
    fft_size: int
    backend: str
    simulation: bool
    # Receiver selection (affects scanning -> user-configurable).
    device_index: int = 0
    # Display of the live scan.
    spectrum_fps: int = 10
    spectrum_bins: int = 1024
    # Recording + retention governance for scan data.
    enable_iq_recording: bool = False
    max_iq_storage_gb: float = 2.0
    retention_days: int = 30

    @model_validator(mode="after")
    def _check_ranges(self) -> ScanConfig:
        if self.start_hz >= self.end_hz:
            raise ValueError("start_hz must be < end_hz")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if not 0.0 < self.noise_floor_alpha <= 1.0:
            raise ValueError("noise_floor_alpha must be in (0, 1]")
        if self.fft_size <= 0 or (self.fft_size & (self.fft_size - 1)) != 0:
            raise ValueError("fft_size must be a positive power of two")
        for lo, hi in self.exclusions:
            if lo >= hi:
                raise ValueError("each exclusion must have low_hz < high_hz")
        if self.device_index < 0:
            raise ValueError("device_index must be >= 0")
        if not 1 <= self.spectrum_fps <= 60:
            raise ValueError("spectrum_fps must be in [1, 60]")
        if not 16 <= self.spectrum_bins <= 8192:
            raise ValueError("spectrum_bins must be in [16, 8192]")
        if self.max_iq_storage_gb < 0:
            raise ValueError("max_iq_storage_gb must be >= 0")
        if self.retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        if self.backend not in {"sim", "rtlsdr", "rtl_power", "soapy"}:
            raise ValueError("backend must be one of: sim, rtlsdr, rtl_power, soapy")
        return self

    @field_validator("gain")
    @classmethod
    def _gain_ok(cls, v: str) -> str:
        v = str(v).strip()
        if v.lower() == "auto":
            return "auto"
        float(v)  # raises ValueError if not a float
        return v

    def range_warnings(self) -> list[str]:
        """Non-fatal compatibility warnings (span vs sample rate, etc.)."""
        warnings: list[str] = []
        span = self.end_hz - self.start_hz
        if span < self.sample_rate:
            warnings.append(
                "scan span is narrower than one sample-rate window; a single dwell "
                "already covers it"
            )
        if self.step_hz and self.step_hz > self.sample_rate:
            warnings.append("step_hz exceeds sample_rate; sweep will leave gaps")
        return warnings


class ScanConfigUpdate(BaseModel):
    """Partial update body for PUT /api/config. All fields optional."""

    start_hz: int | None = None
    end_hz: int | None = None
    step_hz: int | None = None
    sample_rate: int | None = None
    gain: str | None = None
    ppm: int | None = None
    dwell_ms: int | None = None
    threshold_db: float | None = None
    noise_floor_alpha: float | None = None
    exclusions: list[tuple[int, int]] | None = None
    known_channel_widths_hz: list[int] | None = None
    fft_size: int | None = None
    backend: str | None = None
    simulation: bool | None = None
    device_index: int | None = None
    spectrum_fps: int | None = None
    spectrum_bins: int | None = None
    enable_iq_recording: bool | None = None
    max_iq_storage_gb: float | None = None
    retention_days: int | None = None

    @field_validator("gain")
    @classmethod
    def _gain_ok(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = str(v).strip()
        if v.lower() == "auto":
            return "auto"
        float(v)
        return v


class CandidateChannel(BaseModel):
    id: int
    center_hz: int
    bandwidth_hz: int
    current_power_db: float
    peak_power_db: float
    avg_power_db: float
    snr_db: float
    observation_count: int
    first_seen: str
    last_seen: str
    typical_burst_ms: float | None = None
    recurrence_interval_s: float | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    status: ChannelStatus
    fingerprint: Fingerprint | None = None


class Detection(BaseModel):
    id: int
    channel_id: int | None = None
    session_id: int
    timestamp: str
    center_hz: int
    bandwidth_hz: int
    peak_power_db: float
    avg_power_db: float
    snr_db: float
    duration_ms: float | None = None


class Event(BaseModel):
    id: int
    timestamp: str
    kind: str
    message: str
    client_id: str | None = None
    data: dict | None = None


class Session(BaseModel):
    id: int
    started_at: str
    stopped_at: str | None = None
    start_hz: int
    end_hz: int
    backend: str
    simulation: bool


class Recording(BaseModel):
    id: int
    timestamp: str
    path: str
    center_hz: int
    sample_rate: int
    gain: str
    duration_ms: int
    format: str
    bytes: int
    sigmf_meta: dict | None = None


class ClientInfo(BaseModel):
    client_id: str
    display_name: str
    connected_at: str
    is_operator: bool


class DeviceInfo(BaseModel):
    backend: str
    name: str
    index: int
    available: bool
    simulation: bool
    tuner: str
    gains: list[float]
    sample_rates: list[int]
    freq_range_hz: tuple[int, int]


# --- Endpoint request/response envelopes ---


class HealthResponse(BaseModel):
    status: str = "ok"
    simulation: bool
    uptime_s: float
    version: str


class MetricsResponse(BaseModel):
    fft_rate_hz: float
    ws_clients: int
    queue_depth: int
    dropped_frames: int
    scan_progress: float
    db_size_bytes: int
    recording_bytes: int


class ConfigResponse(ScanConfig):
    version: int


class ConfigPutBody(ScanConfigUpdate):
    version: int
    client_id: str


class ScanStartResponse(BaseModel):
    ok: bool = True
    session_id: int


class OkResponse(BaseModel):
    ok: bool = True


class FocusBody(BaseModel):
    center_hz: int
    span_hz: int | None = None
    channel_id: int | None = None


class ChannelsResponse(BaseModel):
    channels: list[CandidateChannel]


class ObservationsResponse(BaseModel):
    observations: list[Detection]


class EventsResponse(BaseModel):
    events: list[Event]


class SessionsResponse(BaseModel):
    sessions: list[Session]


class RecordingsResponse(BaseModel):
    recordings: list[Recording]


class RecordingStartBody(BaseModel):
    duration_ms: int | None = None
    center_hz: int | None = None


class ClientsResponse(BaseModel):
    clients: list[ClientInfo]
    operator_client_id: str | None = None
    count: int


class ControlAcquireBody(BaseModel):
    client_id: str
    display_name: str | None = None


class ControlAcquireResponse(BaseModel):
    ok: bool
    operator_client_id: str | None = None
    lease_expires: str | None = None


class ControlReleaseBody(BaseModel):
    client_id: str


__all__ = [name for name in dir() if name[0].isupper()]
