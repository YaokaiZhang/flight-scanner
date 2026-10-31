#!/usr/bin/env bash
# Build the dbt docs site into a directory (default: _site), from an empty, reachable Postgres
# given by POSTGRES_*. It creates the tables, so the docs show real column types; it needs no data.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mkdir -p "${1:-$ROOT/_site}" && cd "${1:-$ROOT/_site}" && pwd)"
cd "$ROOT"

export FS_AS_OF="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
DBT=(uv run --frozen dbt --quiet)
DIRS=(--project-dir dbt --profiles-dir dbt)
uv run --frozen python -m flight_scanner migrate
"${DBT[@]}" seed "${DIRS[@]}"
"${DBT[@]}" run "${DIRS[@]}"
"${DBT[@]}" docs generate --static "${DIRS[@]}"
cp dbt/target/static_index.html "$OUT/index.html"
