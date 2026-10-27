#!/usr/bin/env bash
# Run the whole Flight Scanner stack inside one Apptainer instance, for hosts without Docker
# (e.g. roihu). The instance supplies the toolchain from docker/flight-scanner.def; inside it,
# scripts/start.sh's local mode runs Postgres, the API, Dagster and the UI as before.
#
#   scripts/apptainer.sh [start|restart|shutdown|status|logs [service]|scan|deploy-databricks|build]
#   (default: start)
#
#   start     build the image if missing, start the instance, then `start.sh up` inside it
#   restart   shutdown, then start
#   shutdown  `start.sh down` inside the instance (clean Postgres stop), then stop the instance
#   build     (re)build the image
#
# Settings: .env as for start.sh, plus
#   FS_SIF        image path               (default $FS_STATE_DIR/flight-scanner.sif)
#   FS_INSTANCE   Apptainer instance name  (default flight-scanner)
#   FS_STATE_DIR, FS_WEB_PORT, FS_API_PORT, FS_DAGSTER_PORT are passed through to start.sh.
# The container's Python venv lives in $FS_STATE_DIR/venv, apart from any host .venv.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() { echo "apptainer.sh: $*" >&2; exit 1; }
say() { echo "==> $*"; }

command -v apptainer >/dev/null 2>&1 || die "apptainer not found on PATH"

STATE="${FS_STATE_DIR:-$ROOT/.local}"
mkdir -p "$STATE"
STATE="$(cd "$STATE" && pwd)"
SIF="${FS_SIF:-$STATE/flight-scanner.sif}"
INSTANCE="${FS_INSTANCE:-flight-scanner}"
DEF="$ROOT/docker/flight-scanner.def"

# Image cache next to the state (not in a small $HOME); build scratch on local disk, since a
# fakeroot build on a setgid project dir fails ("Container ID ... cannot be mapped").
export APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-$STATE/apptainer-cache}"
export APPTAINER_TMPDIR="${APPTAINER_TMPDIR:-${TMPDIR:-/tmp}/$USER-apptainer-tmp}"

instance_running() {
  apptainer instance list 2>/dev/null | awk 'NR > 1 { print $1 }' | grep -qx "$INSTANCE"
}

# Runs start.sh inside the instance with a clean environment plus the settings it reads.
in_instance() {
  local envs=(--env "FS_MODE=local" --env "FS_STATE_DIR=$STATE" --env "UV_PROJECT_ENVIRONMENT=$STATE/venv")
  local var
  for var in FS_WEB_PORT FS_API_PORT FS_DAGSTER_PORT; do
    [ -z "${!var:-}" ] || envs+=(--env "$var=${!var}")
  done
  apptainer exec --cleanenv "${envs[@]}" --pwd "$ROOT" "instance://$INSTANCE" \
    bash "$ROOT/scripts/start.sh" "$@"
}

build() {
  [ -f "$DEF" ] || die "missing $DEF"
  mkdir -p "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR"
  say "building $SIF from docker/flight-scanner.def (takes a few minutes)"
  apptainer build --force --fakeroot "$SIF" "$DEF"
}

start() {
  [ -f .env ] || die "no .env: run \`cp .env.example .env\` and edit it first"
  [ -f "$SIF" ] || build
  if instance_running; then
    echo "    instance $INSTANCE already running"
  else
    say "starting Apptainer instance $INSTANCE"
    # Host network (ports bind to 127.0.0.1 as in local mode). An instance has its own PID
    # namespace, so stopping it also reaps anything start.sh left behind.
    apptainer instance start --cleanenv --bind "$ROOT" --bind "$STATE" \
      "$SIF" "$INSTANCE" >/dev/null
  fi
  in_instance up
  echo "Stop with: scripts/apptainer.sh shutdown"
}

shutdown() {
  if ! instance_running; then
    echo "    instance $INSTANCE is not running"
    return
  fi
  say "stopping services"
  in_instance down || echo "    start.sh down failed; stopping the instance anyway" >&2
  say "stopping Apptainer instance $INSTANCE"
  apptainer instance stop "$INSTANCE" >/dev/null
}

CMD="${1:-start}"
case "$CMD" in
  start) start ;;
  restart) shutdown; start ;;
  shutdown | stop) shutdown ;;
  build) build ;;
  status)
    if instance_running; then
      echo "instance           running ($INSTANCE, $SIF)"
      in_instance status
    else
      echo "instance           stopped"
    fi
    ;;
  logs | scan | deploy-databricks)
    instance_running || die "instance $INSTANCE is not running: scripts/apptainer.sh start"
    in_instance "$CMD" "${2:-}"
    ;;
  *) die "unknown command '$CMD' (start, restart, shutdown, status, logs [service], scan, deploy-databricks, build)" ;;
esac
