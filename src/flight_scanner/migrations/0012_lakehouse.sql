-- Ticket 12: the analytical layer (ADR-0003). Schema `analytics` holds what the lakehouse
-- (Databricks) wrote back; Python owns it (flight_scanner.lakehouse), dbt reads it as a source.

CREATE SCHEMA IF NOT EXISTS analytics;

-- Every daily lakehouse run, including the ones Databricks could not serve.
CREATE TABLE analytics.lakehouse_runs (
    id                  bigserial   PRIMARY KEY,
    engine              text        NOT NULL,            -- e.g. databricks
    as_of               timestamptz NOT NULL,            -- the clock instant the job ran at
    export_date         date        NOT NULL,            -- Helsinki date; the volume folder
    status              text        NOT NULL
                        CHECK (status IN ('published', 'unavailable', 'over_quota', 'failed')),
    detail              text,                            -- why it was not published
    remote_run_id       text,                            -- the engine's job run id
    exported_rows       bigint      NOT NULL DEFAULT 0,
    baselines_published integer     NOT NULL DEFAULT 0,  -- new versions written back
    backtest_deals      integer     NOT NULL DEFAULT 0
);

-- Baseline versions the lakehouse published (append-only, change-only): same key and columns as
-- marts.baseline_versions; `method` is prefixed with the engine (databricks/daily_min_median_60d).
CREATE TABLE analytics.baseline_versions (
    tier                 text          NOT NULL,
    origin_city          text          NOT NULL,
    destination          text          NOT NULL,
    departure_month      date          NOT NULL,
    stay_bucket          text          NOT NULL,
    method               text          NOT NULL,
    median_per_adult_eur numeric(10, 2) NOT NULL,
    mad_eur              numeric(10, 2) NOT NULL,
    observations         bigint        NOT NULL,
    observation_days     bigint        NOT NULL,
    computed_at          timestamptz   NOT NULL,
    run_id               bigint        NOT NULL REFERENCES analytics.lakehouse_runs (id),
    PRIMARY KEY (tier, origin_city, destination, departure_month, stay_bucket, computed_at)
);

-- The latest published lakehouse backtest (one row per Deal; marts.backtest_deals' shape).
CREATE TABLE analytics.backtest_deals (
    run_id                            bigint      NOT NULL REFERENCES analytics.lakehouse_runs (id),
    deal_id                           bigint      NOT NULL,
    watch_id                          bigint      NOT NULL,
    outcome                           text        NOT NULL,
    price_per_adult_eur               numeric(10, 2),
    baseline_per_adult_eur            numeric(10, 2),
    pct_below_baseline                numeric(5, 1),
    later_observation_days            bigint,
    highest_later_price_per_adult_eur numeric(10, 2),
    computed_at                       timestamptz NOT NULL,
    PRIMARY KEY (run_id, deal_id)
);
