"""Everything the pipeline needs from the outside world, injected as one object."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from flight_scanner.clock import Clock
from flight_scanner.db import DbSettings
from flight_scanner.notify.base import Notifier
from flight_scanner.places import ReferenceData, default_reference
from flight_scanner.raw_store import RawStore
from flight_scanner.scan_planner import Budget
from flight_scanner.sources.base import SourceAdapter


@dataclass
class Runtime:
    clock: Clock
    db: DbSettings
    raw_store: RawStore
    work_dir: Path  # scratch space for generated dbt profiles and dbt target dirs
    sources: list[SourceAdapter] = field(default_factory=list)
    notifiers: list[Notifier] = field(default_factory=list)
    # request budget per source (per run and per Helsinki day); absent = unlimited
    source_budgets: dict[str, Budget] = field(default_factory=dict)
    reference: ReferenceData = field(default_factory=default_reference)  # Places (ticket 03)
