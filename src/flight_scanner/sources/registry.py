"""Which source adapters exist and how to build them from settings.

To add a source: implement `SourceAdapter` in `sources/<name>.py` and register a factory here.
Enable it by listing its name in FS_SOURCES. Airline adapters must also check their own explicit
enable flag (spec: off by default).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from flight_scanner.clock import Clock
from flight_scanner.config import Settings
from flight_scanner.sources.base import SourceAdapter
from flight_scanner.sources.replay import ReplayAdapter
from flight_scanner.sources.travelpayouts import TravelpayoutsAdapter


def _fake(settings: Settings, clock: Clock) -> SourceAdapter:
    directory = settings.env.get("FS_FAKE_PAYLOAD_DIR")
    if not directory:
        return ReplayAdapter("fake", clock)
    return ReplayAdapter.from_dir("fake", clock, Path(directory))


def _travelpayouts(settings: Settings, clock: Clock) -> SourceAdapter:
    env = settings.env
    return TravelpayoutsAdapter(
        token=env.get("TRAVELPAYOUTS_TOKEN", ""),
        clock=clock,
        requests_per_minute=float(env.get("FS_TRAVELPAYOUTS_REQUESTS_PER_MINUTE", "60")),
        max_retries=int(env.get("FS_TRAVELPAYOUTS_MAX_RETRIES", "4")),
    )


FACTORIES: dict[str, Callable[[Settings, Clock], SourceAdapter]] = {
    "fake": _fake,
    "travelpayouts": _travelpayouts,
}


def build_sources(settings: Settings, clock: Clock) -> list[SourceAdapter]:
    unknown = set(settings.sources) - FACTORIES.keys()
    if unknown:
        raise ValueError(f"unknown sources in FS_SOURCES: {sorted(unknown)}")
    return [FACTORIES[name](settings, clock) for name in settings.sources]
