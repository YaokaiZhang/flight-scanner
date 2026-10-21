"""The deployed Dagster code location: `dagster ... -m flight_scanner.pipeline.workspace`."""

import dagster as dg

from flight_scanner.clock import SystemClock
from flight_scanner.config import Settings
from flight_scanner.db import migrate
from flight_scanner.deal_context import build_researcher
from flight_scanner.notify.registry import build_notifiers
from flight_scanner.pipeline.definitions import build_definitions
from flight_scanner.pipeline.runtime import Runtime
from flight_scanner.raw_store import RawStore
from flight_scanner.sources.registry import build_sources


def runtime_from_env() -> Runtime:
    settings = Settings.from_env()
    clock = SystemClock()
    return Runtime(
        clock=clock,
        db=settings.db,
        raw_store=RawStore(settings.raw_dir),
        work_dir=settings.work_dir,
        sources=build_sources(settings, clock),
        notifiers=build_notifiers(settings),
        source_budgets=settings.source_budgets,
        researcher=build_researcher(settings),
    )


@dg.definitions
def defs() -> dg.Definitions:
    runtime = runtime_from_env()
    migrate(runtime.db)
    return build_definitions(runtime)
