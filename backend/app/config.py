"""Application settings loaded from environment variables.

All env-var names are FIXED by CONTRACT.md. Defaults match the contract so the
app boots in SIMULATION MODE with zero hardware.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SdrBackendName = Literal["sim", "rtlsdr", "soapy", "rtl_power"]


class Settings(BaseSettings):
    """Environment-driven configuration.

    Reads from process env and an optional `.env` file. Field names use the
    exact env-var names from the contract (case-insensitive).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- SDR / device ---
    sdr_backend: SdrBackendName = "sim"
    sdr_device_index: int = 0
    sdr_sample_rate: int = 2_400_000
    sdr_gain: str = "auto"  # "auto" or float dB as string
    sdr_ppm: int = 0

    # --- Scan defaults ---
    scan_start_hz: int = 867_000_000
    scan_end_hz: int = 870_000_000
    scan_step_hz: int = 0  # 0 = auto
    scan_dwell_ms: int = 120
    detection_threshold_db: float = 6.0
    noise_floor_alpha: float = 0.05

    # --- Storage ---
    database_path: str = "/data/db/channel_detector.sqlite3"
    recording_path: str = "/data/recordings"
    enable_iq_recording: bool = False
    max_iq_storage_gb: float = 2.0
    retention_days: int = 30

    # --- Web / logging ---
    web_port: int = 8080
    log_level: str = "INFO"
    simulation_mode: bool = True

    # --- DSP / streaming ---
    fft_size: int = 2048
    spectrum_fps: int = 10
    spectrum_bins: int = 1024
    cors_origins: str = "*"

    # --- Derived / internal (not from env) ---
    log_dir: str = "/data/logs"
    static_dir: str = Field(
        default_factory=lambda: str(Path(__file__).resolve().parent.parent / "static")
    )

    @field_validator("cors_origins")
    @classmethod
    def _strip_cors(cls, v: str) -> str:
        return v.strip()

    @field_validator("sdr_gain")
    @classmethod
    def _validate_gain(cls, v: str) -> str:
        v = str(v).strip()
        if v.lower() == "auto":
            return "auto"
        try:
            float(v)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError("sdr_gain must be 'auto' or a float in dB") from exc
        return v

    def cors_origin_list(self) -> list[str]:
        """Parse CORS_ORIGINS into a list. '*' -> ['*']."""
        raw = self.cors_origins.strip()
        if raw == "*" or raw == "":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    def gain_value(self) -> str | float:
        """Return 'auto' or a float dB for backend consumption."""
        if self.sdr_gain.lower() == "auto":
            return "auto"
        return float(self.sdr_gain)

    def effective_simulation(self) -> bool:
        """Simulation is forced when backend is 'sim' or SIMULATION_MODE=true."""
        return self.simulation_mode or self.sdr_backend == "sim"

    def db_path(self) -> Path:
        return Path(self.database_path)

    def recordings_dir(self) -> Path:
        return Path(self.recording_path)

    def logs_dir(self) -> Path:
        return Path(self.log_dir)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
