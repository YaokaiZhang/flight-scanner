# No `from __future__ import annotations`: Dagster inspects real type hints
# (context, ResourceParam).

import json

import dagster as dg
from dagster_dbt import DbtCliResource, dbt_assets, get_asset_key_for_model

from flight_scanner import deals, digests, watches
from flight_scanner.clock import today
from flight_scanner.db import connect
from flight_scanner.ingestion import ingest
from flight_scanner.pipeline import dbt as dbt_files
from flight_scanner.pipeline.runtime import Runtime
from flight_scanner.reprocess import ReprocessReport, reprocess

LEG_PRICES = dg.AssetKey(["landing", "leg_prices"])
ROUND_TRIP_PRICES = dg.AssetKey(["landing", "round_trip_prices"])
WATCH_SLOTS = dg.AssetKey(["app", "watch_slots"])


@dg.asset(key=WATCH_SLOTS, group_name="watches")
def watch_slots(context: dg.AssetExecutionContext, runtime: dg.ResourceParam[Runtime]):
    """Concrete trips every active Watch wants priced, expanded for the clock's today."""
    now = runtime.clock.now()
    with connect(runtime.db, autocommit=True) as conn, conn.transaction():
        watches.refresh_expiry(conn, today(runtime.clock))
        slots = watches.slots(conn, today(runtime.clock))
        conn.execute("DELETE FROM app.watch_slots")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO app.watch_slots (watch_id, origin, destination, outbound_date, "
                "return_date, computed_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [(*s, now) for s in slots],
            )
    return dg.MaterializeResult(metadata={"slots": len(slots)})


@dg.multi_asset(
    specs=[
        dg.AssetSpec(LEG_PRICES, deps=[WATCH_SLOTS], group_name="ingestion"),
        dg.AssetSpec(ROUND_TRIP_PRICES, deps=[WATCH_SLOTS], group_name="ingestion"),
    ]
)
def source_prices(context: dg.AssetExecutionContext, runtime: dg.ResourceParam[Runtime]):
    """Plan, fetch, store raw and parse for every enabled source; one outage never stops others."""
    with connect(runtime.db, autocommit=True) as conn:
        slots = [
            watches.WatchSlot(**r)
            for r in conn.execute(
                "SELECT watch_id, origin, destination, outbound_date, return_date "
                "FROM app.watch_slots"
            )
        ]
        report = ingest(
            conn,
            runtime.sources,
            watches.demands(slots),
            runtime.raw_store,
            runtime.source_budgets,
        )
    meta = {"sources": dg.MetadataValue.json(report.as_metadata())}
    yield dg.MaterializeResult(asset_key=LEG_PRICES, metadata=meta)
    yield dg.MaterializeResult(asset_key=ROUND_TRIP_PRICES, metadata=meta)


def build_definitions(runtime: Runtime) -> dg.Definitions:
    manifest = dbt_files.ensure_manifest()

    @dbt_assets(manifest=manifest)
    def dbt_models(
        context: dg.AssetExecutionContext, dbt: DbtCliResource, runtime: dg.ResourceParam[Runtime]
    ):
        as_of = runtime.clock.now().isoformat()
        yield from dbt.cli(
            ["build", "--vars", json.dumps({"as_of": as_of})], context=context
        ).stream()

    candidates_key = get_asset_key_for_model([dbt_models], "candidates")

    @dg.asset(key=["app", "deals"], deps=[candidates_key], group_name="deals")
    def deals_asset(runtime: dg.ResourceParam[Runtime]):
        """Candidates become Deals (Unverified until Verification exists), one per dedup key."""
        with connect(runtime.db, autocommit=True) as conn:
            new = deals.record_deals(conn, runtime.clock.now())
        return dg.MaterializeResult(metadata={"new_deals": new})

    @dg.asset(key=["app", "alerts"], deps=[dg.AssetKey(["app", "deals"])], group_name="deals")
    def alerts_asset(runtime: dg.ResourceParam[Runtime]):
        """Hand every not-yet-alerted Deal to the notifiers."""
        with connect(runtime.db, autocommit=True) as conn:
            sent = deals.send_alerts(conn, runtime.notifiers, runtime.clock.now())
        return dg.MaterializeResult(metadata={"alerts_sent": sent})

    @dg.asset(key=["app", "digests"], deps=[dg.AssetKey(["app", "deals"])], group_name="deals")
    def digests_asset(runtime: dg.ResourceParam[Runtime]):
        """Send the daily Digest of each Watch in Digest mode once it is due."""
        with connect(runtime.db, autocommit=True) as conn:
            sent = digests.send_digests(conn, runtime.notifiers, runtime.clock.now())
        return dg.MaterializeResult(metadata={"digests_sent": sent})

    assets = [watch_slots, source_prices, dbt_models, deals_asset, alerts_asset, digests_asset]
    scan_job = dg.define_asset_job("scan", selection=dg.AssetSelection.assets(*assets))
    # dbt only (seeds, staging, history, marts): used by `rebuild` after re-parsing the raw store
    rebuild_job = dg.define_asset_job("rebuild", selection=dg.AssetSelection.assets(dbt_models))
    profiles = dbt_files.write_profiles(runtime.db, runtime.work_dir / "dbt-profiles")
    return dg.Definitions(
        assets=assets,
        jobs=[scan_job, rebuild_job],
        schedules=[dg.ScheduleDefinition(job=scan_job, cron_schedule="*/30 * * * *")],
        resources={
            "runtime": runtime,
            "dbt": DbtCliResource(
                project_dir=str(dbt_files.DBT_PROJECT_DIR),
                profiles_dir=str(profiles),
                dbt_executable=dbt_files.dbt_executable(),
            ),
        },
    )


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


def rebuild(runtime: Runtime, instance: dg.DagsterInstance | None = None) -> ReprocessReport:
    """Re-parse every raw payload of the configured sources, then rebuild all dbt models."""
    with connect(runtime.db, autocommit=True) as conn:
        report = reprocess(conn, runtime.raw_store, {s.name: s.parse for s in runtime.sources})
    _execute(runtime, "rebuild", instance)
    return report
