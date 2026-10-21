-- Ticket 10: data-quality gates and the data-health page.

-- What each executed scan task landed (prices parsed) and, when it failed, why.
ALTER TABLE app.scan_tasks
    ADD COLUMN rows   integer,
    ADD COLUMN error  text;

-- The slices whose data currently fails a data-quality check (replaced after every scan).
-- origin null = the whole source. dbt (marts.trip_prices) leaves out a gated slice's prices, so it
-- cannot produce Candidates; every other source and origin is unaffected.
CREATE TABLE app.quality_gates (
    check_name  text        NOT NULL,
    source      text        NOT NULL,
    origin      text,
    detail      text        NOT NULL,
    since       timestamptz NOT NULL,  -- first consecutive evaluation it failed in
    checked_at  timestamptz NOT NULL
);

-- Every failing slice of every evaluation (append-only, pruned after 30 days): the data-health
-- page's recent check failures.
CREATE TABLE app.quality_failures (
    id          bigserial   PRIMARY KEY,
    checked_at  timestamptz NOT NULL,
    check_name  text        NOT NULL,
    source      text        NOT NULL,
    origin      text,
    detail      text        NOT NULL
);
CREATE INDEX quality_failures_checked_at ON app.quality_failures (checked_at);

-- The checks read a source's recent Fare observations.
CREATE INDEX leg_prices_source_observed ON landing.leg_prices (source, observed_at);
CREATE INDEX round_trip_prices_source_observed ON landing.round_trip_prices (source, observed_at);
