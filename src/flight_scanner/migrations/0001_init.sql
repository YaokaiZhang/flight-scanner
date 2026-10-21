-- Walking skeleton schema. dbt owns the `staging` and `marts` schemas.
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS landing;

-- A Watch: Place sets and Trip-pattern preset are stored as given (jsonb) so later tickets can
-- widen them without migrations; derived, query-friendly facts go in typed columns.
CREATE TABLE app.watches (
    id                    bigserial PRIMARY KEY,
    name                  text        NOT NULL,
    origins               jsonb       NOT NULL,
    destinations          jsonb       NOT NULL,
    trip_pattern          jsonb       NOT NULL,
    adults                integer     NOT NULL CHECK (adults BETWEEN 1 AND 9),
    price_threshold_eur   numeric(10, 2),
    price_threshold_basis text CHECK (price_threshold_basis IN ('total', 'per_adult')),
    status                text        NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    created_at            timestamptz NOT NULL,
    updated_at            timestamptz NOT NULL
);

-- Concrete trips each active Watch wants priced "today" (rebuilt by the pipeline each run).
CREATE TABLE app.watch_slots (
    watch_id       bigint NOT NULL REFERENCES app.watches (id) ON DELETE CASCADE,
    origin         text   NOT NULL,
    destination    text   NOT NULL,
    outbound_date  date   NOT NULL,
    return_date    date,
    computed_at    timestamptz NOT NULL
);
CREATE UNIQUE INDEX watch_slots_key
    ON app.watch_slots (watch_id, origin, destination, outbound_date, coalesce(return_date, '0001-01-01'));

-- Manifest of immutable raw payload files (the bytes live in the raw store on disk).
CREATE TABLE landing.raw_payloads (
    id          bigserial PRIMARY KEY,
    source      text        NOT NULL,
    fetched_at  timestamptz NOT NULL,
    request     jsonb       NOT NULL,
    path        text        NOT NULL UNIQUE,
    sha256      text        NOT NULL
);

-- Source rows as parsed by an adapter, before normalisation (dbt staging normalises).
CREATE TABLE landing.leg_prices (
    payload_id      bigint      NOT NULL REFERENCES landing.raw_payloads (id),
    source          text        NOT NULL,
    observed_at     timestamptz NOT NULL,
    origin          text        NOT NULL,
    destination     text        NOT NULL,
    departure_date  date        NOT NULL,
    price           numeric(10, 2) NOT NULL,
    currency        text        NOT NULL,
    adults          integer     NOT NULL DEFAULT 1,
    airline         text,
    stops           integer,
    duration_min    integer
);

CREATE TABLE landing.round_trip_prices (
    payload_id      bigint      NOT NULL REFERENCES landing.raw_payloads (id),
    source          text        NOT NULL,
    observed_at     timestamptz NOT NULL,
    origin          text        NOT NULL,
    destination     text        NOT NULL,
    departure_date  date        NOT NULL,
    return_date     date        NOT NULL,
    price           numeric(10, 2) NOT NULL,
    currency        text        NOT NULL,
    adults          integer     NOT NULL DEFAULT 1,
    airline         text,
    stops           integer,
    duration_min    integer
);

-- A Deal, keyed by the Alert dedup key. Written by the pipeline; read by the API.
CREATE TABLE app.deals (
    id                  bigserial PRIMARY KEY,
    watch_id            bigint      NOT NULL REFERENCES app.watches (id) ON DELETE CASCADE,
    origin              text        NOT NULL,
    destination         text        NOT NULL,
    outbound_date       date        NOT NULL,
    return_date         date,
    price_per_adult_eur numeric(10, 2) NOT NULL,
    price_total_eur     numeric(10, 2) NOT NULL,
    adults              integer     NOT NULL,
    source              text        NOT NULL,
    observed_at         timestamptz NOT NULL,
    verification        text        NOT NULL DEFAULT 'unverified'
                        CHECK (verification IN ('verified', 'unverified')),
    baseline_tier       text,
    detected_at         timestamptz NOT NULL
);
CREATE UNIQUE INDEX deals_dedup_key
    ON app.deals (watch_id, origin, destination, outbound_date, coalesce(return_date, '0001-01-01'));

-- Every Alert handed to a notifier.
CREATE TABLE app.alerts (
    id        bigserial PRIMARY KEY,
    deal_id   bigint      NOT NULL REFERENCES app.deals (id) ON DELETE CASCADE,
    channel   text        NOT NULL,
    sent_at   timestamptz NOT NULL,
    price_total_eur numeric(10, 2) NOT NULL
);
