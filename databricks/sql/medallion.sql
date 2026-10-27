-- Bronze and silver (ADR-0003), run by the analytics job before the dbt (gold) task.
-- Parameter :catalog (default flight_scanner). The daily export lands on the volume as
--   /Volumes/<catalog>/bronze/exports/<export_date>/<schema>.<table>.parquet
-- bronze.<table>: every export ever loaded (append-only; COPY INTO skips files already loaded),
--                 plus _export_date (from the folder) and _ingested_at.
-- silver.<table>: the latest export of each table (a full snapshot), named as the dbt models
--                 and sources expect them on Databricks (generate_schema_name, sources.yml).
-- COPY INTO needs a literal path: with a catalog other than flight_scanner, edit the
-- '/Volumes/flight_scanner/...' paths below too.
-- Keep in sync with flight_scanner.lakehouse.export.EXPORT_TABLES (a test checks it).

USE CATALOG IDENTIFIER(:catalog);
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE VOLUME IF NOT EXISTS bronze.exports;
CREATE VOLUME IF NOT EXISTS bronze.raw;  -- the raw archive (flight_scanner/raw_archive.py)

-- staging.stg_leg_prices
CREATE TABLE IF NOT EXISTS bronze.stg_leg_prices;
COPY INTO bronze.stg_leg_prices
FROM (
    SELECT *, to_date(regexp_extract(_metadata.file_path, '/(\\d{4}-\\d{2}-\\d{2})/', 1)) AS _export_date,
           current_timestamp() AS _ingested_at
    FROM '/Volumes/flight_scanner/bronze/exports/'
)
FILEFORMAT = PARQUET
PATTERN = '*/staging.stg_leg_prices.parquet'
FORMAT_OPTIONS ('mergeSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');
CREATE OR REPLACE TABLE silver.stg_leg_prices AS
SELECT * EXCEPT (_export_date, _ingested_at) FROM bronze.stg_leg_prices
WHERE _export_date = (SELECT max(_export_date) FROM bronze.stg_leg_prices);

-- staging.stg_round_trip_prices
CREATE TABLE IF NOT EXISTS bronze.stg_round_trip_prices;
COPY INTO bronze.stg_round_trip_prices
FROM (
    SELECT *, to_date(regexp_extract(_metadata.file_path, '/(\\d{4}-\\d{2}-\\d{2})/', 1)) AS _export_date,
           current_timestamp() AS _ingested_at
    FROM '/Volumes/flight_scanner/bronze/exports/'
)
FILEFORMAT = PARQUET
PATTERN = '*/staging.stg_round_trip_prices.parquet'
FORMAT_OPTIONS ('mergeSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');
CREATE OR REPLACE TABLE silver.stg_round_trip_prices AS
SELECT * EXCEPT (_export_date, _ingested_at) FROM bronze.stg_round_trip_prices
WHERE _export_date = (SELECT max(_export_date) FROM bronze.stg_round_trip_prices);

-- staging.stg_price_insights
CREATE TABLE IF NOT EXISTS bronze.stg_price_insights;
COPY INTO bronze.stg_price_insights
FROM (
    SELECT *, to_date(regexp_extract(_metadata.file_path, '/(\\d{4}-\\d{2}-\\d{2})/', 1)) AS _export_date,
           current_timestamp() AS _ingested_at
    FROM '/Volumes/flight_scanner/bronze/exports/'
)
FILEFORMAT = PARQUET
PATTERN = '*/staging.stg_price_insights.parquet'
FORMAT_OPTIONS ('mergeSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');
CREATE OR REPLACE TABLE silver.stg_price_insights AS
SELECT * EXCEPT (_export_date, _ingested_at) FROM bronze.stg_price_insights
WHERE _export_date = (SELECT max(_export_date) FROM bronze.stg_price_insights);

-- history.leg_price_history
CREATE TABLE IF NOT EXISTS bronze.leg_price_history;
COPY INTO bronze.leg_price_history
FROM (
    SELECT *, to_date(regexp_extract(_metadata.file_path, '/(\\d{4}-\\d{2}-\\d{2})/', 1)) AS _export_date,
           current_timestamp() AS _ingested_at
    FROM '/Volumes/flight_scanner/bronze/exports/'
)
FILEFORMAT = PARQUET
PATTERN = '*/history.leg_price_history.parquet'
FORMAT_OPTIONS ('mergeSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');
CREATE OR REPLACE TABLE silver.leg_price_history AS
SELECT * EXCEPT (_export_date, _ingested_at) FROM bronze.leg_price_history
WHERE _export_date = (SELECT max(_export_date) FROM bronze.leg_price_history);

-- history.round_trip_price_history
CREATE TABLE IF NOT EXISTS bronze.round_trip_price_history;
COPY INTO bronze.round_trip_price_history
FROM (
    SELECT *, to_date(regexp_extract(_metadata.file_path, '/(\\d{4}-\\d{2}-\\d{2})/', 1)) AS _export_date,
           current_timestamp() AS _ingested_at
    FROM '/Volumes/flight_scanner/bronze/exports/'
)
FILEFORMAT = PARQUET
PATTERN = '*/history.round_trip_price_history.parquet'
FORMAT_OPTIONS ('mergeSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');
CREATE OR REPLACE TABLE silver.round_trip_price_history AS
SELECT * EXCEPT (_export_date, _ingested_at) FROM bronze.round_trip_price_history
WHERE _export_date = (SELECT max(_export_date) FROM bronze.round_trip_price_history);

-- app.watch_slots
CREATE TABLE IF NOT EXISTS bronze.watch_slots;
COPY INTO bronze.watch_slots
FROM (
    SELECT *, to_date(regexp_extract(_metadata.file_path, '/(\\d{4}-\\d{2}-\\d{2})/', 1)) AS _export_date,
           current_timestamp() AS _ingested_at
    FROM '/Volumes/flight_scanner/bronze/exports/'
)
FILEFORMAT = PARQUET
PATTERN = '*/app.watch_slots.parquet'
FORMAT_OPTIONS ('mergeSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');
CREATE OR REPLACE TABLE silver.watch_slots AS
SELECT * EXCEPT (_export_date, _ingested_at) FROM bronze.watch_slots
WHERE _export_date = (SELECT max(_export_date) FROM bronze.watch_slots);

-- app.quality_gates
CREATE TABLE IF NOT EXISTS bronze.quality_gates;
COPY INTO bronze.quality_gates
FROM (
    SELECT *, to_date(regexp_extract(_metadata.file_path, '/(\\d{4}-\\d{2}-\\d{2})/', 1)) AS _export_date,
           current_timestamp() AS _ingested_at
    FROM '/Volumes/flight_scanner/bronze/exports/'
)
FILEFORMAT = PARQUET
PATTERN = '*/app.quality_gates.parquet'
FORMAT_OPTIONS ('mergeSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');
CREATE OR REPLACE TABLE silver.quality_gates AS
SELECT * EXCEPT (_export_date, _ingested_at) FROM bronze.quality_gates
WHERE _export_date = (SELECT max(_export_date) FROM bronze.quality_gates);

-- app.deals
CREATE TABLE IF NOT EXISTS bronze.deals;
COPY INTO bronze.deals
FROM (
    SELECT *, to_date(regexp_extract(_metadata.file_path, '/(\\d{4}-\\d{2}-\\d{2})/', 1)) AS _export_date,
           current_timestamp() AS _ingested_at
    FROM '/Volumes/flight_scanner/bronze/exports/'
)
FILEFORMAT = PARQUET
PATTERN = '*/app.deals.parquet'
FORMAT_OPTIONS ('mergeSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');
CREATE OR REPLACE TABLE silver.deals AS
SELECT * EXCEPT (_export_date, _ingested_at) FROM bronze.deals
WHERE _export_date = (SELECT max(_export_date) FROM bronze.deals);

-- app.alerts
CREATE TABLE IF NOT EXISTS bronze.alerts;
COPY INTO bronze.alerts
FROM (
    SELECT *, to_date(regexp_extract(_metadata.file_path, '/(\\d{4}-\\d{2}-\\d{2})/', 1)) AS _export_date,
           current_timestamp() AS _ingested_at
    FROM '/Volumes/flight_scanner/bronze/exports/'
)
FILEFORMAT = PARQUET
PATTERN = '*/app.alerts.parquet'
FORMAT_OPTIONS ('mergeSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');
CREATE OR REPLACE TABLE silver.alerts AS
SELECT * EXCEPT (_export_date, _ingested_at) FROM bronze.alerts
WHERE _export_date = (SELECT max(_export_date) FROM bronze.alerts);

-- ref.airports
CREATE TABLE IF NOT EXISTS bronze.airports;
COPY INTO bronze.airports
FROM (
    SELECT *, to_date(regexp_extract(_metadata.file_path, '/(\\d{4}-\\d{2}-\\d{2})/', 1)) AS _export_date,
           current_timestamp() AS _ingested_at
    FROM '/Volumes/flight_scanner/bronze/exports/'
)
FILEFORMAT = PARQUET
PATTERN = '*/ref.airports.parquet'
FORMAT_OPTIONS ('mergeSchema' = 'true')
COPY_OPTIONS ('mergeSchema' = 'true');
CREATE OR REPLACE TABLE silver.airports AS
SELECT * EXCEPT (_export_date, _ingested_at) FROM bronze.airports
WHERE _export_date = (SELECT max(_export_date) FROM bronze.airports);
