"""Seam 1: the analytical layer (ADR-0003). The daily lakehouse job exports history and staging
as Parquet to Databricks, which rebuilds Baselines and the backtest with the shared dbt models;
its Baselines are written back as new versions and used for detection. Databricks is never on
the alerting path: when it is unavailable or over quota, detection carries on with the last
published Baselines.

`pipeline.use_databricks()` answers the real Databricks adapter with `FakeDatabricks`, which runs
the job (bronze/silver load of the uploaded Parquet, then the shared dbt models) on a scratch
Postgres database. The clock starts at 2026-10-21 09:00Z.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from flight_scanner.api import create_app

START = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
NOV_DATES = ["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"]
WATCH = {
    "name": "Barcelona",
    "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
    "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
    "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-20"},
}
OPERATIONAL = "daily_min_median_60d"  # the method of Baselines recomputed on verda each scan
PUBLISHED = "databricks/daily_min_median_60d"  # ... and of those Databricks published


def payload(price_of) -> dict:
    return {
        "currency": "EUR",
        "prices": [
            {"origin": "HEL", "destination": "BCN", "depart_date": d, "price": price_of(j)}
            for j, d in enumerate(NOV_DATES)
        ],
    }


def published_at(deal: dict) -> datetime:
    return datetime.fromisoformat(deal["baseline"]["computed_at"])


def three_weeks_of_normal_prices(pipeline) -> None:
    pipeline.create_watch(WATCH)
    for i in range(21):  # around 100 EUR, a little noise from day to day
        pipeline.clock.set(START + timedelta(days=i))
        pipeline.fake.replay(payload(lambda j, i=i: 95 + (i + j) % 3 * 5))
        pipeline.collect() if i < 20 else pipeline.run()  # the last a full scan (dbt built)


def scan_with_a_cheap_fare(pipeline, day: int) -> dict:
    """A scan on `day` with a fare half below normal; returns the Deal as the API shows it."""
    pipeline.clock.set(START + timedelta(days=day))
    pipeline.fake.replay(payload(lambda j: 50 if NOV_DATES[j] == "2026-11-20" else 100))
    pipeline.run()
    with TestClient(create_app(pipeline.db, pipeline.clock)) as api:
        [deal] = [d for d in api.get("/deals").json() if d["outbound_date"] == "2026-11-20"]
    return deal


def test_the_daily_job_publishes_databricks_baselines_that_detection_then_uses(pipeline):
    three_weeks_of_normal_prices(pipeline)
    databricks = pipeline.use_databricks()

    pipeline.clock.set(
        START + timedelta(days=21, hours=-6)
    )  # early morning, before the day's scans
    run = pipeline.run_lakehouse()

    assert run.status == "published"
    # history and staging went to the Unity Catalog volume as Parquet, one file per table
    assert {
        "staging.stg_leg_prices.parquet",
        "staging.stg_round_trip_prices.parquet",
        "history.leg_price_history.parquet",
        "history.round_trip_price_history.parquet",
    } <= {name for _, name in databricks.uploaded}
    assert {export_date for export_date, _ in databricks.uploaded} == {"2026-11-11"}
    assert run.baselines_published >= 1  # new Baseline versions written back to Postgres

    deal = scan_with_a_cheap_fare(pipeline, day=21)

    assert deal["baseline"]["tier"] == "route"
    assert deal["baseline"]["per_adult_eur"] == 100
    assert deal["baseline"]["method"] == PUBLISHED
    assert published_at(deal) == datetime(2026, 11, 11, 3, tzinfo=UTC)


def test_a_second_unchanged_run_writes_no_new_baseline_versions(pipeline):
    three_weeks_of_normal_prices(pipeline)
    pipeline.use_databricks()
    first = pipeline.run_lakehouse()

    second = pipeline.run_lakehouse()

    assert first.baselines_published >= 1
    assert (second.status, second.baselines_published) == ("published", 0)


def test_when_databricks_is_over_quota_detection_continues_on_the_last_published_baselines(
    pipeline,
):
    three_weeks_of_normal_prices(pipeline)
    databricks = pipeline.use_databricks()
    pipeline.clock.set(START + timedelta(days=21, hours=-6))
    assert pipeline.run_lakehouse().status == "published"

    databricks.over_quota()  # Free Edition shut compute off for the day
    pipeline.clock.set(START + timedelta(days=22, hours=-6))
    run = pipeline.run_lakehouse()  # the daily job records it and does not fail

    assert run.status == "over_quota"
    deal = scan_with_a_cheap_fare(pipeline, day=22)
    assert deal["baseline"]["method"] == PUBLISHED
    assert published_at(deal) == datetime(2026, 11, 11, 3, tzinfo=UTC)  # the last published one
    assert deal["baseline"]["per_adult_eur"] == 100


def test_unavailable_databricks_never_stops_detection(pipeline):
    three_weeks_of_normal_prices(pipeline)
    databricks = pipeline.use_databricks()
    databricks.go_down()

    run = pipeline.run_lakehouse()

    assert run.status == "unavailable"
    deal = scan_with_a_cheap_fare(pipeline, day=21)  # nothing was ever published
    assert (deal["baseline"]["method"], deal["baseline"]["per_adult_eur"]) == (OPERATIONAL, 100)


def test_published_baselines_older_than_a_week_give_way_to_the_operational_recompute(pipeline):
    three_weeks_of_normal_prices(pipeline)
    databricks = pipeline.use_databricks()
    pipeline.clock.set(START + timedelta(days=21, hours=-6))
    pipeline.run_lakehouse()
    databricks.over_quota()  # and stays so

    deal = scan_with_a_cheap_fare(pipeline, day=29)  # 8 days without a new publication

    assert deal["baseline"]["method"] == OPERATIONAL
