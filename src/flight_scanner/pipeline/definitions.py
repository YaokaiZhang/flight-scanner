# No `from __future__ import annotations`: Dagster inspects real type hints
# (context, ResourceParam).

import dagster as dg
from dagster_dbt import DbtCliResource, dbt_assets, get_asset_key_for_model

from flight_scanner import (
    data_quality,
    deals,
    digests,
    scan_planner,
    source_health,
    verification,
    watches,
)
from flight_scanner.clock import today
from flight_scanner.db import connect
from flight_scanner.deal_context import add_deal_context
from flight_scanner.ingestion import ingest
from flight_scanner.lakehouse import LakehouseRun, latest_run, run_daily
from flight_scanner.pipeline import dbt as dbt_files
from flight_scanner.pipeline.runtime import Runtime
from flight_scanner.reprocess import ReprocessReport, reprocess

LEG_PRICES = dg.AssetKey(["landing", "leg_prices"])
ROUND_TRIP_PRICES = dg.AssetKey(["landing", "round_trip_prices"])
WATCH_SLOTS = dg.AssetKey(["app", "watch_slots"])
SCAN_PLAN = dg.AssetKey(["app", "scan_plan"])
DEAL_CONTEXT = dg.AssetKey(["app", "deal_context"])
VERIFICATION = dg.AssetKey(["app", "verification"])
REF_AIRPORTS = dg.AssetKey(["ref", "airports"])
QUALITY_GATES = dg.AssetKey(["app", "quality_gates"])
# what the lakehouse published (dbt source analytics.baseline_versions -> effective_baselines)
LAKEHOUSE = dg.AssetKey(["analytics", "baseline_versions"])


@dg.asset(key=REF_AIRPORTS, group_name="reference")
def ref_airports(runtime: dg.ResourceParam[Runtime]):
    """City and country of every airport (Baseline keys), from the bundled Places snapshot.

    Rewritten only when the reference data version changes."""
    ref = runtime.reference
    with connect(runtime.db, autocommit=True) as conn, conn.transaction():
        stored = conn.execute("SELECT DISTINCT reference_version AS v FROM ref.airports").fetchall()
        if [r["v"] for r in stored] == [ref.version]:
            return dg.MaterializeResult(metadata={"version": ref.version, "rewritten": False})
        conn.execute("DELETE FROM ref.airports")
        with (
            conn.cursor() as cur,
            cur.copy(
                "COPY ref.airports (code, city, country, reference_version) FROM STDIN"
            ) as copy,
        ):
            for a in ref.airports.values():
                copy.write_row((a.code, a.city, a.country, ref.version))
    return dg.MaterializeResult(
        metadata={"version": ref.version, "rewritten": True, "airports": len(ref.airports)}
    )


@dg.asset(key=WATCH_SLOTS, group_name="watches")
def watch_slots(context: dg.AssetExecutionContext, runtime: dg.ResourceParam[Runtime]):
    """Concrete trips every active Watch wants priced, expanded for the clock's today."""
    now = runtime.clock.now()
    with connect(runtime.db, autocommit=True) as conn, conn.transaction():
        watches.refresh_expiry(conn, today(runtime.clock))
        slots = watches.slots(conn, today(runtime.clock), runtime.reference)
        conn.execute("DELETE FROM app.watch_slots")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO app.watch_slots (watch_id, origin, destination, outbound_date, "
                "return_date, computed_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [(*s, now) for s in slots],
            )
    return dg.MaterializeResult(metadata={"slots": len(slots)})


@dg.asset(key=SCAN_PLAN, deps=[WATCH_SLOTS], group_name="ingestion")
def scan_plan(context: dg.AssetExecutionContext, runtime: dg.ResourceParam[Runtime]):
    """Shared, ranked scan tasks per source; those over a source's budget are recorded skipped.
    Ranking reads last run's history and trip prices (dbt runs after ingestion)."""
    with connect(runtime.db, autocommit=True) as conn, conn.transaction():
        slots = [
            watches.WatchSlot(**r)
            for r in conn.execute(
                "SELECT watch_id, origin, destination, outbound_date, return_date "
                "FROM app.watch_slots"
            )
        ]
        plan_id = scan_planner.plan(
            conn,
            slots,
            runtime.sources,
            runtime.source_budgets,
            runtime.clock.now(),
            today(runtime.clock),
        )
        counts = {
            f"{r['source']}.{r['status']}": r["n"]
            for r in conn.execute(
                "SELECT source, status, count(*) AS n FROM app.scan_tasks WHERE plan_id = %s "
                "GROUP BY source, status",
                (plan_id,),
            )
        }
    return dg.MaterializeResult(metadata={"plan_id": plan_id, **counts})


@dg.multi_asset(
    specs=[
        dg.AssetSpec(LEG_PRICES, deps=[SCAN_PLAN], group_name="ingestion"),
        dg.AssetSpec(ROUND_TRIP_PRICES, deps=[SCAN_PLAN], group_name="ingestion"),
    ]
)
def source_prices(context: dg.AssetExecutionContext, runtime: dg.ResourceParam[Runtime]):
    """Fetch, store raw and parse the scan plan's scheduled tasks; one outage never stops others.
    A source that was turned away (bot protection) is disabled (`source_health`)."""
    with connect(runtime.db, autocommit=True) as conn:
        plan_id = scan_planner.latest_plan_id(conn)
        tasks = scan_planner.scheduled(conn, plan_id) if plan_id is not None else []
        report = ingest(conn, runtime.sources, tasks, runtime.raw_store)
        scan_planner.finish(
            conn, report.task_status, runtime.clock.now(), report.task_rows, report.task_errors
        )
        for outcome in report.outcomes:
            if outcome.blocked:  # disabled until the owner re-enables it
                source_health.block(conn, outcome.source, outcome.error, runtime.clock.now())
    meta = {"sources": dg.MetadataValue.json(report.as_metadata())}
    yield dg.MaterializeResult(asset_key=LEG_PRICES, metadata=meta)
    yield dg.MaterializeResult(asset_key=ROUND_TRIP_PRICES, metadata=meta)


@dg.asset(
    key=QUALITY_GATES,
    deps=[LEG_PRICES, ROUND_TRIP_PRICES],
    group_name="ingestion",
    check_specs=[
        dg.AssetCheckSpec(name, asset=QUALITY_GATES, description=description)
        for name, description in data_quality.CHECKS.items()
    ],
)
def quality_gates(runtime: dg.ResourceParam[Runtime]):
    """Data-quality checks over what the scan sources landed. A failing slice (source, origin or
    the whole source) is gated: dbt's trip prices leave it out, so it cannot produce Candidates,
    and the other slices carry on. The checks never stop the run (severity WARN)."""
    now = runtime.clock.now()
    with connect(runtime.db, autocommit=True) as conn, conn.transaction():
        gates = data_quality.evaluate(conn, [s.name for s in runtime.sources], now)
    failing = {
        name: [g.as_metadata() for g in gates if g.check_name == name]
        for name in data_quality.CHECKS
    }
    checks = [
        dg.AssetCheckResult(
            check_name=name,
            passed=not slices,
            severity=dg.AssetCheckSeverity.WARN,
            metadata={"failing_slices": dg.MetadataValue.json(slices)},
        )
        for name, slices in failing.items()
    ]
    return dg.MaterializeResult(metadata={"gates": len(gates)}, check_results=checks)


@dg.asset(key=LAKEHOUSE, group_name="analytics")
def lakehouse_asset(runtime: dg.ResourceParam[Runtime]):
    """Daily (ADR-0003): export history and staging as Parquet to the lakehouse (Databricks),
    which rebuilds Baselines and the backtest with the shared dbt models; its Baselines are
    written back as new versions. Never on the alerting path: an unavailable or over-quota
    lakehouse is recorded and detection keeps the last published Baselines."""
    if runtime.lakehouse is None:
        return dg.MaterializeResult(metadata={"status": "off"})
    with connect(runtime.db, autocommit=True) as conn:
        run = run_daily(conn, runtime.lakehouse, runtime.work_dir, runtime.clock.now())
    return dg.MaterializeResult(
        metadata={
            "engine": run.engine,
            "status": run.status,
            "detail": run.detail or "",
            "exported_rows": run.exported_rows,
            "baselines_published": run.baselines_published,
            "backtest_deals": run.backtest_deals,
        }
    )


BACKTEST_MODELS = "backtest_deals"


def build_definitions(runtime: Runtime) -> dg.Definitions:
    manifest = dbt_files.ensure_manifest()

    # Every dbt model but the backtest, which judges this run's Deals and Alerts (dbt sources
    # app.deals / app.alerts = the assets below) and so runs after them.
    @dbt_assets(manifest=manifest, exclude=BACKTEST_MODELS)
    def dbt_models(
        context: dg.AssetExecutionContext, dbt: DbtCliResource, runtime: dg.ResourceParam[Runtime]
    ):
        yield from dbt_files.build(context, dbt, runtime)

    @dbt_assets(manifest=manifest, select=BACKTEST_MODELS, name="dbt_backtest")
    def dbt_backtest(
        context: dg.AssetExecutionContext, dbt: DbtCliResource, runtime: dg.ResourceParam[Runtime]
    ):
        yield from dbt_files.build(context, dbt, runtime)

    candidates_key = get_asset_key_for_model([dbt_models], "candidates")

    @dg.asset(key=["app", "deals"], deps=[candidates_key], group_name="deals")
    def deals_asset(runtime: dg.ResourceParam[Runtime]):
        """Candidates become Deals, one per dedup key, with their Alert rounds."""
        with connect(runtime.db, autocommit=True) as conn:
            new = deals.record_deals(conn, runtime.clock.now())
        return dg.MaterializeResult(metadata={"new_deals": new})

    @dg.asset(key=VERIFICATION, deps=[dg.AssetKey(["app", "deals"])], group_name="deals")
    def verification_asset(runtime: dg.ResourceParam[Runtime]):
        """Check the best due Deals live within the verifier's budget: Verified, failed (never
        alerted) or Unverified. The answers are stored as Fare observations / Price insights."""
        with connect(runtime.db, autocommit=True) as conn:
            counts = verification.verify_deals(
                conn, runtime.verifier, runtime.raw_store, runtime.clock.now()
            )
        return dg.MaterializeResult(
            metadata={
                "verifier": runtime.verifier.name if runtime.verifier else "none",
                **counts,
            }
        )

    @dg.asset(key=DEAL_CONTEXT, deps=[VERIFICATION], group_name="deals")
    def deal_context_asset(runtime: dg.ResourceParam[Runtime]):
        """Optional "why is this cheap?" line for new Deals; waits at most the cap."""
        with connect(runtime.db, autocommit=True) as conn:
            counts = add_deal_context(
                conn, runtime.researcher, runtime.clock.now(), runtime.deal_context_timeout
            )
        return dg.MaterializeResult(
            metadata={
                "enabled": runtime.researcher is not None,
                **{f"context_{k}": v for k, v in counts.items()},
            }
        )

    @dg.asset(key=["app", "alerts"], deps=[DEAL_CONTEXT], group_name="deals")
    def alerts_asset(runtime: dg.ResourceParam[Runtime]):
        """Hand every not-yet-alerted Deal to the notifiers."""
        with connect(runtime.db, autocommit=True) as conn:
            sent = deals.send_alerts(conn, runtime.notifiers, runtime.clock.now())
        return dg.MaterializeResult(metadata={"alerts_sent": sent})

    @dg.asset(key=["app", "digests"], deps=[DEAL_CONTEXT], group_name="deals")
    def digests_asset(runtime: dg.ResourceParam[Runtime]):
        """Send the daily Digest of each Watch in Digest mode once it is due."""
        with connect(runtime.db, autocommit=True) as conn:
            sent = digests.send_digests(conn, runtime.notifiers, runtime.clock.now())
        return dg.MaterializeResult(metadata={"digests_sent": sent})

    assets = [
        ref_airports,
        watch_slots,
        scan_plan,
        source_prices,
        quality_gates,
        dbt_models,
        deals_asset,
        verification_asset,
        deal_context_asset,
        alerts_asset,
        digests_asset,
        dbt_backtest,
    ]
    scan_job = dg.define_asset_job("scan", selection=dg.AssetSelection.assets(*assets))
    # prices only (no dbt, detection or Alerts): builds history between full scans
    collect_job = dg.define_asset_job(
        "collect", selection=dg.AssetSelection.assets(watch_slots, scan_plan, source_prices)
    )
    # reference data and dbt (seeds, staging, history, Baselines, marts): used by `rebuild`
    # after re-parsing the raw store
    rebuild_job = dg.define_asset_job(
        "rebuild", selection=dg.AssetSelection.assets(ref_airports, dbt_models, dbt_backtest)
    )
    # the analytical layer, once a day before the morning's scans; separate from the scan job
    lakehouse_job = dg.define_asset_job("lakehouse", selection=[LAKEHOUSE])
    profiles = dbt_files.write_profiles(runtime.db, runtime.work_dir / "dbt-profiles")
    return dg.Definitions(
        assets=[*assets, lakehouse_asset],
        jobs=[scan_job, collect_job, rebuild_job, lakehouse_job],
        sensors=_feedback_sensors(runtime),
        schedules=[
            dg.ScheduleDefinition(job=scan_job, cron_schedule="*/30 * * * *"),
            dg.ScheduleDefinition(
                job=lakehouse_job, cron_schedule="15 4 * * *", execution_timezone="Europe/Helsinki"
            ),
        ],
        resources={
            "runtime": runtime,
            "dbt": dbt_files.DbtCli(
                project_dir=str(dbt_files.DBT_PROJECT_DIR),
                profiles_dir=str(profiles),
                dbt_executable=dbt_files.dbt_executable(),
            ),
        },
    )


def _feedback_sensors(runtime: Runtime) -> list[dg.SensorDefinition]:
    """Collect 👍/👎 taps from notifiers that support it (Telegram) every 30 s; launches no runs."""
    collectors = [n for n in runtime.notifiers if hasattr(n, "collect_feedback")]
    if not collectors:
        return []

    @dg.sensor(
        name="telegram_feedback",
        minimum_interval_seconds=30,
        default_status=dg.DefaultSensorStatus.RUNNING,
    )
    def telegram_feedback(context: dg.SensorEvaluationContext):
        with connect(runtime.db, autocommit=True) as conn:
            n = sum(c.collect_feedback(conn, runtime.clock.now()) for c in collectors)
        return dg.SkipReason(f"recorded {n} ratings")

    return [telegram_feedback]


def _execute(
    runtime: Runtime, job_name: str, instance: dg.DagsterInstance | None
) -> dg.ExecuteInProcessResult:
    defs = build_definitions(runtime)
    job = defs.resolve_job_def(job_name)
    if instance is None:
        tmp = runtime.work_dir / "dagster"
        tmp.mkdir(parents=True, exist_ok=True)
        instance = dg.DagsterInstance.ephemeral(tempdir=str(tmp))
    return job.execute_in_process(instance=instance)


def run_once(
    runtime: Runtime, instance: dg.DagsterInstance | None = None
) -> dg.ExecuteInProcessResult:
    """Materialise the whole scan in-process (seam-1 harness, e2e stack, manual runs)."""
    return _execute(runtime, "scan", instance)


def collect(
    runtime: Runtime, instance: dg.DagsterInstance | None = None
) -> dg.ExecuteInProcessResult:
    """Only collect prices (Watch slots and sources): no dbt, detection or Alerts."""
    return _execute(runtime, "collect", instance)


def rebuild(runtime: Runtime, instance: dg.DagsterInstance | None = None) -> ReprocessReport:
    """Re-parse every raw payload of the configured sources, then rebuild all dbt models."""
    with connect(runtime.db, autocommit=True) as conn:
        parsers = {s.name: s.parse for s in runtime.sources}
        if runtime.verifier is not None:
            parsers[runtime.verifier.name] = runtime.verifier.parse
        report = reprocess(conn, runtime.raw_store, parsers)
    _execute(runtime, "rebuild", instance)
    return report


def run_lakehouse(
    runtime: Runtime, instance: dg.DagsterInstance | None = None
) -> LakehouseRun | None:
    """Run the daily lakehouse job once; returns the run it recorded (None when it is off)."""
    _execute(runtime, "lakehouse", instance)
    with connect(runtime.db, autocommit=True) as conn:
        return latest_run(conn) if runtime.lakehouse is not None else None
