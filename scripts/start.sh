#!/usr/bin/env bash
# Start, stop and inspect the whole Flight Scanner stack: Postgres, the HTTP API, Dagster
# (webserver + daemon, which runs the scan every 30 min and the lakehouse job at 04:15) and the UI.
#
#   scripts/start.sh [up|down|status|scan|logs [service]]      (default: up)
#
# Two modes, picked automatically (override with FS_MODE=docker|local):
#   docker  `docker compose` with compose.yaml, the deployment on verda.
#   local   no Docker: a private Postgres (unix socket only) plus the services as background
#           processes, for a laptop or a shared login node. Needs PostgreSQL 16 (initdb, pg_ctl),
#           uv and Node 22 on PATH, e.g. `conda activate flight-scanner`.
#
# Settings come from .env (copy .env.example). Local mode keeps its state in FS_STATE_DIR
# (default .local/): Postgres data, raw payloads, Dagster storage, logs and pid files.
# Local ports (127.0.0.1 only): FS_WEB_PORT=3000, FS_API_PORT=8000, FS_DAGSTER_PORT=3001.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() { echo "start.sh: $*" >&2; exit 1; }
say() { echo "==> $*"; }

[ -f .env ] || die "no .env: run \`cp .env.example .env\` and edit it first"
set -a
# shellcheck disable=SC1091
. ./.env
set +a

MODE="${FS_MODE:-}"
if [ -z "$MODE" ]; then
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    MODE=docker
  else
    MODE=local
  fi
fi

# Polls URL until it answers (any HTTP status) or TIMEOUT seconds pass.
wait_for() {
  local name="$1" url="$2" timeout="${3:-120}" i
  for ((i = 0; i < timeout; i++)); do
    if curl -s -o /dev/null --max-time 2 "$url"; then
      echo "    $name is up: $url"
      return 0
    fi
    sleep 1
  done
  return 1
}

# --- docker mode ---------------------------------------------------------------------------------
docker_cmd() {
  case "$1" in
    up)
      [ "${POSTGRES_PASSWORD:-}" != "change-me" ] || die "set POSTGRES_PASSWORD in .env"
      say "building and starting the Compose stack"
      docker compose up -d --build
      wait_for api http://127.0.0.1:8000/health 180 || die "API did not come up: docker compose logs api"
      wait_for dagster http://127.0.0.1:3001/server_info 180 || die "Dagster did not come up"
      wait_for web http://127.0.0.1:3000 180 || die "UI did not come up: docker compose logs web"
      cat <<EOF

Flight Scanner is running (scans every 30 min; the first one starts on the next half hour).
  UI       http://127.0.0.1:3000
  Dagster  http://127.0.0.1:3001   (run a scan now: scripts/start.sh scan)
  API      http://127.0.0.1:8000
From another machine: ssh -L 3000:127.0.0.1:3000 -L 3001:127.0.0.1:3001 <this host>
EOF
      ;;
    down) docker compose down ;;
    status) docker compose ps ;;
    scan) docker compose exec dagster-daemon python -m flight_scanner scan ;;
    logs) docker compose logs -f --tail=100 ${2:+"$2"} ;;
  esac
}

# --- local mode ----------------------------------------------------------------------------------
WEB_PORT="${FS_WEB_PORT:-3000}"
API_PORT="${FS_API_PORT:-8000}"
DAGSTER_PORT="${FS_DAGSTER_PORT:-3001}"
SERVICES=(api dagster-webserver dagster-daemon web)

local_env() {
  STATE="$(mkdir -p "${FS_STATE_DIR:-$ROOT/.local}" && cd "${FS_STATE_DIR:-$ROOT/.local}" && pwd)"
  PGDATA="$STATE/pg"
  PGSOCK="$STATE/pg-socket"
  LOGS="$STATE/logs"
  PIDS="$STATE/pids"
  # Postgres listens on a unix socket in the state dir only (no TCP, owner-only), so on a shared
  # host nobody else can reach it and no password is needed.
  export POSTGRES_HOST="$PGSOCK" POSTGRES_PORT="${POSTGRES_PORT:-5432}"
  export POSTGRES_USER="${POSTGRES_USER:-flightscanner}" POSTGRES_DB="${POSTGRES_DB:-flightscanner}"
  export FS_DATA_DIR="${FS_DATA_DIR:-$STATE/data}"
  export FS_DBT_PROJECT_DIR="$ROOT/dbt"
  export DAGSTER_HOME="$STATE/dagster"
  export API_URL="http://127.0.0.1:$API_PORT"
  export NEXT_TELEMETRY_DISABLED=1
  export PATH="$ROOT/.venv/bin:$PATH"
}

need() { command -v "$1" >/dev/null 2>&1 || die "$1 not found on PATH ($2)"; }

pid_alive() { [ -f "$PIDS/$1" ] && kill -0 "$(cat "$PIDS/$1")" 2>/dev/null; }

start_bg() {
  local name="$1"; shift
  if pid_alive "$name"; then
    echo "    $name already running (pid $(cat "$PIDS/$name"))"
    return
  fi
  nohup "$@" >"$LOGS/$name.log" 2>&1 &
  echo $! >"$PIDS/$name"
  echo "    started $name (pid $!, log $LOGS/$name.log)"
}

local_postgres_up() {
  need initdb "PostgreSQL 16 server binaries; e.g. conda activate flight-scanner"
  mkdir -p "$PGSOCK" && chmod 700 "$PGSOCK"
  if [ ! -f "$PGDATA/PG_VERSION" ]; then
    say "creating the Postgres cluster in $PGDATA"
    initdb -D "$PGDATA" -U "$POSTGRES_USER" --auth=trust --encoding=UTF8 >"$LOGS/initdb.log"
  fi
  if ! pg_ctl -D "$PGDATA" status >/dev/null 2>&1; then
    say "starting Postgres"
    pg_ctl -D "$PGDATA" -l "$LOGS/postgres.log" -w start \
      -o "-c listen_addresses='' -k $PGSOCK -p $POSTGRES_PORT -c unix_socket_permissions=0700" \
      >/dev/null
  fi
  if ! psql -h "$PGSOCK" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'" | grep -q 1; then
    createdb -h "$PGSOCK" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" "$POSTGRES_DB"
  fi
}

local_up() {
  need uv "https://docs.astral.sh/uv/"
  need npm "Node 22"
  need curl "curl"
  mkdir -p "$LOGS" "$PIDS" "$DAGSTER_HOME" "$FS_DATA_DIR"
  local_postgres_up

  say "installing Python dependencies (uv sync)"
  uv sync --frozen --no-dev --quiet
  say "applying migrations"
  python -m flight_scanner migrate

  # Same run limit as docker/dagster.yaml (scans never overlap); local storage is SQLite here.
  cat >"$DAGSTER_HOME/dagster.yaml" <<'EOF'
run_coordinator:
  module: dagster._core.run_coordinator
  class: QueuedRunCoordinator
  config:
    max_concurrent_runs: 1
telemetry:
  enabled: false
EOF

  if [ ! -d web/node_modules ]; then
    say "installing UI dependencies (npm ci)"
    (cd web && npm ci --no-audit --no-fund --loglevel=error)
  fi
  if [ ! -f web/.next/BUILD_ID ] || [ -n "$(find web/app web/components web/lib -newer web/.next/BUILD_ID -print -quit)" ]; then
    say "building the UI (next build)"
    (cd web && npm run build >"$LOGS/web-build.log" 2>&1) || die "UI build failed: $LOGS/web-build.log"
  fi

  say "starting services"
  start_bg api uvicorn flight_scanner.api.main:app --host 127.0.0.1 --port "$API_PORT"
  start_bg dagster-webserver dagster-webserver -h 127.0.0.1 -p "$DAGSTER_PORT" \
    -m flight_scanner.pipeline.workspace
  start_bg dagster-daemon dagster-daemon run -m flight_scanner.pipeline.workspace
  start_bg web bash -c "cd web && exec npx next start --hostname 127.0.0.1 --port $WEB_PORT"

  wait_for api "http://127.0.0.1:$API_PORT/health" 60 || die "API did not come up: $LOGS/api.log"
  wait_for dagster "http://127.0.0.1:$DAGSTER_PORT/server_info" 180 \
    || die "Dagster did not come up: $LOGS/dagster-webserver.log"
  wait_for web "http://127.0.0.1:$WEB_PORT" 60 || die "UI did not come up: $LOGS/web.log"
  cat <<EOF

Flight Scanner is running locally (scans every 30 min while the Dagster daemon runs).
  UI       http://127.0.0.1:$WEB_PORT
  Dagster  http://127.0.0.1:$DAGSTER_PORT   (run a scan now: scripts/start.sh scan)
  API      http://127.0.0.1:$API_PORT
  State    $STATE
Stop with: scripts/start.sh down
EOF
}

local_down() {
  local name pid
  for name in "${SERVICES[@]}"; do
    if pid_alive "$name"; then
      pid="$(cat "$PIDS/$name")"
      # Stop the process and its children (next start / dagster run workers).
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill -TERM "$pid" 2>/dev/null || true
      echo "    stopped $name (pid $pid)"
    fi
    rm -f "$PIDS/$name"
  done
  if [ -f "$PGDATA/PG_VERSION" ] && pg_ctl -D "$PGDATA" status >/dev/null 2>&1; then
    pg_ctl -D "$PGDATA" -m fast -w stop >/dev/null && echo "    stopped postgres"
  fi
}

local_status() {
  local name
  if [ -f "$PGDATA/PG_VERSION" ] && pg_ctl -D "$PGDATA" status >/dev/null 2>&1; then
    echo "postgres           running ($PGDATA)"
  else
    echo "postgres           stopped"
  fi
  for name in "${SERVICES[@]}"; do
    if pid_alive "$name"; then
      printf '%-18s running (pid %s)\n' "$name" "$(cat "$PIDS/$name")"
    else
      printf '%-18s stopped\n' "$name"
    fi
  done
}

local_cmd() {
  local_env
  case "$1" in
    up) local_up ;;
    down) local_down ;;
    status) local_status ;;
    scan)
      pg_ctl -D "$PGDATA" status >/dev/null 2>&1 || die "Postgres is not running: scripts/start.sh up"
      python -m flight_scanner scan
      ;;
    logs) tail -n 100 -F "$LOGS/${2:-api}.log" ;;
  esac
}

CMD="${1:-up}"
case "$CMD" in
  up | down | status | scan | logs) ;;
  *) die "unknown command '$CMD' (up, down, status, scan, logs [service])" ;;
esac
case "$MODE" in
  docker) docker_cmd "$CMD" "${2:-}" ;;
  local) local_cmd "$CMD" "${2:-}" ;;
  *) die "FS_MODE must be docker or local, not '$MODE'" ;;
esac
