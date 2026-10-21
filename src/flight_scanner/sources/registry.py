"""Which source adapters exist and how to build them from settings.

To add a source: implement `SourceAdapter` in `sources/<name>.py` and register a factory here.
Enable it by listing its name in FS_SOURCES. The unofficial airline adapters (Ryanair, Wizz) also
need their own explicit flag (ENABLE_FLAGS, e.g. FS_ENABLE_RYANAIR=true): without it they are left
out with a warning and everything else runs as usual (ADR-0002: off by default, ToS note in
`.env.example`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from flight_scanner.clock import Clock
from flight_scanner.config import Settings
from flight_scanner.sources.base import SourceAdapter
from flight_scanner.sources.replay import ReplayAdapter
from flight_scanner.sources.ryanair import RyanairAdapter
from flight_scanner.sources.travelpayouts import TravelpayoutsAdapter
from flight_scanner.sources.wizz import WizzAdapter

log = logging.getLogger(__name__)


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


def _airline_http_options(env: dict[str, str], prefix: str) -> dict:
    return {
        "requests_per_minute": float(env.get(f"{prefix}_REQUESTS_PER_MINUTE") or "6"),
        "max_retries": int(env.get(f"{prefix}_MAX_RETRIES") or "2"),
    }


def _ryanair(settings: Settings, clock: Clock) -> SourceAdapter:
    return RyanairAdapter(clock, **_airline_http_options(settings.env, "FS_RYANAIR"))


def _wizz(settings: Settings, clock: Clock) -> SourceAdapter:
    return WizzAdapter(
        clock,
        api_url=settings.env.get("FS_WIZZ_API_URL") or None,
        **_airline_http_options(settings.env, "FS_WIZZ"),
    )


FACTORIES: dict[str, Callable[[Settings, Clock], SourceAdapter]] = {
    "fake": _fake,
    "travelpayouts": _travelpayouts,
    "ryanair": _ryanair,
    "wizz": _wizz,
}

# Sources that run only when the owner also sets this flag to "true" (unofficial endpoints).
ENABLE_FLAGS = {"ryanair": "FS_ENABLE_RYANAIR", "wizz": "FS_ENABLE_WIZZ"}


def _enabled(settings: Settings, name: str) -> bool:
    flag = ENABLE_FLAGS.get(name)
    if flag is None or settings.env.get(flag, "").strip().lower() == "true":
        return True
    log.warning(
        "source %s is listed in FS_SOURCES but stays off: set %s=true to enable it "
        "(unofficial airline endpoint; read the terms note in .env.example first)",
        name,
        flag,
    )
    return False


def build_sources(settings: Settings, clock: Clock) -> list[SourceAdapter]:
    unknown = set(settings.sources) - FACTORIES.keys()
    if unknown:
        raise ValueError(f"unknown sources in FS_SOURCES: {sorted(unknown)}")
    return [
        FACTORIES[name](settings, clock) for name in settings.sources if _enabled(settings, name)
    ]
