-- Runs once on an empty Postgres volume: a separate database for Dagster's own storage.
-- Keep in sync with docker/postgres-init.sql.
CREATE DATABASE dagster;
