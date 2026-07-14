"""ScanConfig validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import schemas


def _valid_kwargs() -> dict:
    return {
        "start_hz": 867_000_000,
        "end_hz": 870_000_000,
        "step_hz": 0,
        "sample_rate": 2_400_000,
        "gain": "auto",
        "ppm": 0,
        "dwell_ms": 120,
        "threshold_db": 6.0,
        "noise_floor_alpha": 0.05,
        "exclusions": [],
        "known_channel_widths_hz": [],
        "fft_size": 2048,
        "backend": "sim",
        "simulation": True,
    }


def test_valid_config() -> None:
    cfg = schemas.ScanConfig(**_valid_kwargs())
    assert cfg.start_hz < cfg.end_hz


def test_start_must_be_less_than_end() -> None:
    kw = _valid_kwargs()
    kw["start_hz"] = kw["end_hz"]
    with pytest.raises(ValidationError):
        schemas.ScanConfig(**kw)


def test_fft_size_must_be_power_of_two() -> None:
    kw = _valid_kwargs()
    kw["fft_size"] = 1000
    with pytest.raises(ValidationError):
        schemas.ScanConfig(**kw)


def test_noise_floor_alpha_range() -> None:
    kw = _valid_kwargs()
    kw["noise_floor_alpha"] = 0.0
    with pytest.raises(ValidationError):
        schemas.ScanConfig(**kw)


def test_gain_accepts_float_string() -> None:
    kw = _valid_kwargs()
    kw["gain"] = "32.5"
    cfg = schemas.ScanConfig(**kw)
    assert cfg.gain == "32.5"


def test_invalid_gain_rejected() -> None:
    kw = _valid_kwargs()
    kw["gain"] = "loud"
    with pytest.raises(ValidationError):
        schemas.ScanConfig(**kw)


def test_exclusion_ordering() -> None:
    kw = _valid_kwargs()
    kw["exclusions"] = [(870_000_000, 869_000_000)]
    with pytest.raises(ValidationError):
        schemas.ScanConfig(**kw)


def test_range_warnings_narrow_span() -> None:
    kw = _valid_kwargs()
    kw["end_hz"] = kw["start_hz"] + 1000  # narrower than sample rate
    cfg = schemas.ScanConfig(**kw)
    warnings = cfg.range_warnings()
    assert any("narrower" in w for w in warnings)
