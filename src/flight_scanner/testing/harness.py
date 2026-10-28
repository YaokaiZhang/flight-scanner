"""Seam-1 harness: drive the real pipeline with fake sources and a recording notifier.

    h = PipelineHarness(db, tmp_path, start=datetime(2026, 10, 21, 9, tzinfo=UTC))
    watch = h.create_watch({...})                         # through the Watches module
    h.fake.replay(Path("payload.json"), route=("HEL", "BCN"))
    h.clock.advance(minutes=30)
    h.run()                                               # real Postgres, dbt and Dagster
    h.collect()                                           # prices only (builds history fast)
    h.notifier.alerts                                     # what came out

Swap reference data with `h.use_reference(ReferenceData.load(dir))`.
Add more fake sources with `h.add_source(ReplayAdapter("other", h.clock))`, and channel stand-ins
with `h.add_notifier(RecordingNotifier("telegram"))` (gets only Watches that chose Telegram).
Turn on Deal context with `h.use_researcher(FakeResearcher({...}), timeout_seconds=...)`.
Turn on Verification with `google = h.use_google_flights(daily_quota=...)`: the real SerpApi
adapter answered by `FakeGoogleFlights` (`google.offer(...)`, `google.asked`).
Turn on the analytical layer with `databricks = h.use_databricks()` (the real Databricks adapter
answered by `FakeDatabricks`; `databricks.over_quota()`, `.go_down()`) and run its daily job with
`h.run_lakehouse()` (returns the recorded `LakehouseRun`).
dbt's data tests are skipped for speed; `h.run_dbt_data_tests()` runs them like production does.
Pass a `dbt_parse_dir` shared by harnesses on the same database name to skip dbt's full parse.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import dagster as dg

from flight_scanner import watches
from flight_scanner.clock import FakeClock
from flight_scanner.db import DbSettings, connect
from flight_scanner.deal_context import DEAL_CONTEXT_TIMEOUT, Researcher
from flight_scanner.lakehouse import DatabricksLakehouse, LakehouseRun
from flight_scanner.notify.base import Notifier, RecordingNotifier
from flight_scanner.pipeline import Runtime, collect, rebuild, run_lakehouse, run_once
from flight_scanner.places import ReferenceData
from flight_scanner.raw_store import RawStore
from flight_scanner.reprocess import ReprocessReport
from flight_scanner.scan_planner import Budget
from flight_scanner.sources.base import SourceAdapter
from flight_scanner.sources.replay import ReplayAdapter
from flight_scanner.sources.serpapi import DAILY_QUOTA, MONTHLY_QUOTA, SerpApiAdapter
from flight_scanner.testing.fake_databricks import FakeDatabricks
from flight_scanner.testing.fake_serpapi import FakeGoogleFlights


class PipelineHarness:
    def __init__(
        self, db: DbSettings, work_dir: Path, start: datetime, dbt_parse_dir: Path | None = None
    ):
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
            dbt_data_tests=False,  # speed: production runs them every scan; see run_dbt_data_tests
            dbt_parse_dir=dbt_parse_dir,
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

    def use_google_flights(
        self, daily_quota: int = DAILY_QUOTA, monthly_quota: int = MONTHLY_QUOTA
    ) -> FakeGoogleFlights:
        """Verify Candidates through the SerpApi adapter against a fake Google Flights."""
        google = FakeGoogleFlights()
        self.runtime.verifier = SerpApiAdapter(
            "test-key",
            self.clock,
            transport=google,
            sleep=lambda s: None,
            daily_quota=daily_quota,
            monthly_quota=monthly_quota,
        )
        return google

    def use_databricks(self) -> FakeDatabricks:
        """Turn on the daily lakehouse job: the Databricks adapter against a fake workspace."""
        databricks = FakeDatabricks(self.db, self.runtime.work_dir)
        self.runtime.lakehouse = DatabricksLakehouse(
            FakeDatabricks.HOST,
            "test-token",
            job_id=1,
            warehouse_id="test-warehouse",
            transport=databricks,
            sleep=lambda s: None,
        )
        return databricks

    def run_lakehouse(self) -> LakehouseRun | None:
        """The daily lakehouse job at the clock's current instant (None when it is off)."""
        return run_lakehouse(self.runtime)

    def run_dbt_data_tests(self, on: bool = True) -> None:
        """Run dbt's data tests in later scans, as production does (off by default: slow)."""
        self.runtime.dbt_data_tests = on

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

    def collect(self) -> dg.ExecuteInProcessResult:
        """A scan that only collects prices (history for Baselines); detects nothing."""
        self.last_result = collect(self.runtime)
        return self.last_result

    def rebuild(self) -> ReprocessReport:
        """Re-parse the raw store into landing and rebuild every dbt model (no fetching)."""
        return rebuild(self.runtime)
