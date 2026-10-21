"""Seam-1 harness: drive the real pipeline with fake sources and a recording notifier.

    h = PipelineHarness(db, tmp_path, start=datetime(2026, 10, 21, 9, tzinfo=UTC))
    watch = h.create_watch({...})                         # through the Watches module
    h.fake.replay(Path("payload.json"), route=("HEL", "BCN"))
    h.clock.advance(minutes=30)
    h.run()                                               # real Postgres, dbt and Dagster
    h.notifier.alerts                                     # what came out

Swap reference data with `h.use_reference(ReferenceData.load(dir))`.
Add more fake sources with `h.add_source(ReplayAdapter("other", h.clock))`, and channel stand-ins
with `h.add_notifier(RecordingNotifier("telegram"))` (gets only Watches that chose Telegram).
Turn on Deal context with `h.use_researcher(FakeResearcher({...}), timeout_seconds=...)`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import dagster as dg

from flight_scanner import watches
from flight_scanner.clock import FakeClock
from flight_scanner.db import DbSettings, connect
from flight_scanner.deal_context import DEAL_CONTEXT_TIMEOUT, Researcher
from flight_scanner.notify.base import Notifier, RecordingNotifier
from flight_scanner.pipeline import Runtime, rebuild, run_once
from flight_scanner.places import ReferenceData
from flight_scanner.raw_store import RawStore
from flight_scanner.reprocess import ReprocessReport
from flight_scanner.scan_planner import Budget
from flight_scanner.sources.base import SourceAdapter
from flight_scanner.sources.replay import ReplayAdapter


class PipelineHarness:
    def __init__(self, db: DbSettings, work_dir: Path, start: datetime):
        self.db = db
        self.clock = FakeClock(start)
        self.fake = ReplayAdapter("fake", self.clock)
        self.notifier = RecordingNotifier()
        self.raw_store = RawStore(Path(work_dir) / "raw")
        self.runtime = Runtime(
            clock=self.clock,
            db=db,
            raw_store=self.raw_store,
            work_dir=Path(work_dir),
            sources=[self.fake],
            notifiers=[self.notifier],
        )
        self.last_result: dg.ExecuteInProcessResult | None = None

    def add_source(self, adapter: SourceAdapter) -> SourceAdapter:
        self.runtime.sources.append(adapter)
        return adapter

    def add_notifier(self, notifier: Notifier) -> Notifier:
        self.runtime.notifiers.append(notifier)
        return notifier

    def set_budget(
        self, source: str, per_run: int | None = None, per_day: int | None = None
    ) -> None:
        """Limit a source's requests for later runs (None: unlimited)."""
        self.runtime.source_budgets[source] = Budget(per_run, per_day)

    def use_researcher(
        self, researcher: Researcher | None, timeout_seconds: float = DEAL_CONTEXT_TIMEOUT
    ) -> None:
        """Turn on Deal context with this researcher (e.g. `FakeResearcher`) and wait cap."""
        self.runtime.researcher = researcher
        self.runtime.deal_context_timeout = timeout_seconds

    def use_reference(self, reference: ReferenceData) -> None:
        """Swap the Places reference data used by later runs (and Watch validation)."""
        self.runtime.reference = reference

    def create_watch(self, spec: watches.WatchSpec | dict) -> watches.Watch:
        if isinstance(spec, dict):
            spec = watches.WatchSpec.model_validate(spec)
        with connect(self.db) as conn:
            return watches.create(conn, spec, self.clock, self.runtime.reference)

    def get_watch(self, watch_id: int) -> watches.Watch | None:
        with connect(self.db) as conn:
            return watches.get(conn, watch_id)

    def run(self) -> dg.ExecuteInProcessResult:
        """One full scan at the clock's current instant. Raises if any step fails."""
        self.last_result = run_once(self.runtime)
        return self.last_result

    def rebuild(self) -> ReprocessReport:
        """Re-parse the raw store into landing and rebuild every dbt model (no fetching)."""
        return rebuild(self.runtime)
