-- Ticket 05: Baselines and Deal detection.

-- Reference data dbt needs for Baseline keys: the city and country of every airport. Written by
-- the pipeline from the bundled Places snapshot (flight_scanner.places) whenever its version
-- changes; `city` is null for airports OurAirports gives no municipality.
CREATE SCHEMA IF NOT EXISTS ref;
CREATE TABLE ref.airports (
    code              text PRIMARY KEY,
    city              text,
    country           text NOT NULL,
    reference_version text NOT NULL
);

-- Which Baseline version a Deal was judged against (baseline_tier and baseline_per_adult_eur
-- already exist): the version is (tier, key, computed_at) in marts.baseline_versions.
ALTER TABLE app.deals
    ADD COLUMN baseline_method           text,
    ADD COLUMN baseline_computed_at      timestamptz,
    ADD COLUMN baseline_observations     integer,
    ADD COLUMN baseline_observation_days integer;
