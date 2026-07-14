"""SDR backend abstraction.

RECEIVE-ONLY. Backends expose read-only tuning + IQ capture. There is no
transmit path anywhere in this package by design.
"""

from .base import SdrBackend, SdrInfo, TuneRange

__all__ = ["SdrBackend", "SdrInfo", "TuneRange"]
