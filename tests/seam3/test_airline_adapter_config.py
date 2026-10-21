"""Seam 3: the airline adapters stay off unless the owner explicitly enables them (ADR-0002)."""

import logging
from datetime import UTC, datetime

import pytest

from flight_scanner.clock import FakeClock
from flight_scanner.config import Settings
from flight_scanner.sources.registry import build_sources
from flight_scanner.sources.ryanair import RyanairAdapter
from flight_scanner.sources.wizz import WizzAdapter

CLOCK = FakeClock(datetime(2026, 10, 21, 9, tzinfo=UTC))


def names(env: dict) -> list[str]:
    return [s.name for s in build_sources(Settings.from_env(env), CLOCK)]


def test_listing_an_airline_source_is_not_enough_to_enable_it(caplog):
    with caplog.at_level(logging.WARNING):
        assert names({"FS_SOURCES": "ryanair,wizz"}) == []
    assert "FS_ENABLE_RYANAIR" in caplog.text and "FS_ENABLE_WIZZ" in caplog.text


def test_the_enable_flag_alone_does_not_add_a_source():
    assert names({"FS_ENABLE_RYANAIR": "true", "FS_ENABLE_WIZZ": "true"}) == []


@pytest.mark.parametrize("value", ["false", "0", "", "no"])
def test_anything_but_an_explicit_yes_keeps_it_off(value):
    assert names({"FS_SOURCES": "ryanair", "FS_ENABLE_RYANAIR": value}) == []


def test_listed_and_enabled_airline_sources_are_built():
    sources = build_sources(
        Settings.from_env(
            {
                "FS_SOURCES": "ryanair,wizz",
                "FS_ENABLE_RYANAIR": "true",
                "FS_ENABLE_WIZZ": "TRUE",
                "FS_WIZZ_API_URL": "https://be.wizzair.com/28.0.0",
            }
        ),
        CLOCK,
    )
    assert [type(s) for s in sources] == [RyanairAdapter, WizzAdapter]


def test_other_sources_run_without_them():
    assert names({"FS_SOURCES": "fake,ryanair"}) == ["fake"]
