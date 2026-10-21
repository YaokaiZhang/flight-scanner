"""Source adapters: one per price source, all behind `SourceAdapter` (see `base.py`)."""

from flight_scanner.sources.base import (
    LegPrice,
    ParsedPrices,
    RawPayload,
    RoundTripPrice,
    ScanRequest,
    SourceAdapter,
    SourceUnavailable,
)

__all__ = [
    "LegPrice",
    "ParsedPrices",
    "RawPayload",
    "RoundTripPrice",
    "ScanRequest",
    "SourceAdapter",
    "SourceUnavailable",
]
