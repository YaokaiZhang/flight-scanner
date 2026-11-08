#!/usr/bin/env bash
# Deploy the app to an OpenShift project, using a managed PostgreSQL outside the cluster.
#
#   infra/deploy-openshift.sh              deploy the images of the checked-out commit
#   infra/deploy-openshift.sh --tag <tag>  deploy the images of another commit (a rollback)
#
# The images are built by GitHub Actions (.github/workflows/images.yml) on every push to main
# and tagged with the first 12 characters of the commit. Nothing is built here.
#
# Needs: kubectl (or oc) logged in, with your project as the current one (`oc project <name>`),
# and git. Reads the app's settings and secrets from .env at the repo root, which must also say
# where the database is: POSTGRES_HOST, POSTGRES_PORT and PGSSLMODE (infra/openshift.md).
#
# Environment overrides:
#   FS_ENV_FILE        another .env file
#   FS_NAMESPACE       deploy to this project instead of the current one
#   FS_IMAGE_REGISTRY  pull images from here (default: ghcr.io/<owner of the origin remote>)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/infra/k8s/.deploy" # generated overlay; git-ignored
ENV_FILE="${FS_ENV_FILE:-$ROOT/.env}"
TAG=""
if [[ "${1:-}" == "--tag" ]]; then
  TAG="${2:?--tag needs a value}"
fi

# shellcheck source=infra/lib.sh
source "$ROOT/infra/lib.sh"

need kubectl git
check_env_file

# --- The database --------------------------------------------------------------------------------
# Without the in-cluster Postgres component, .env is the only place the app learns where the
# database is.
PG_HOST=$(env_value POSTGRES_HOST)
case "$PG_HOST" in
  "" | localhost | 127.0.0.1 | postgres)
    die "set POSTGRES_HOST in $ENV_FILE to your managed PostgreSQL's address (now: '${PG_HOST}')" ;;
esac
# The connection leaves the cluster, so it should be encrypted. libpq (used by the app, Dagster
# and dbt alike) reads PGSSLMODE from the environment. Make the choice explicit.
case "$(env_value PGSSLMODE)" in
  require | verify-ca | verify-full) ;;
  disable | allow | prefer)
    echo "warning: PGSSLMODE=$(env_value PGSSLMODE): the database connection may be unencrypted" >&2 ;;
  *) die "set PGSSLMODE=require in $ENV_FILE (or verify-full; PGSSLMODE=disable if the database has no TLS)" ;;
esac
[[ -n "$(env_value DAGSTER_PG_DB)" ]] || die "set DAGSTER_PG_DB in $ENV_FILE (Dagster's database, e.g. dagster)"

# --- Where to deploy -----------------------------------------------------------------------------
# `oc project <name>` (or `oc login`) stores the project as the namespace of kubectl's context.
NS="${FS_NAMESPACE:-$(kubectl config view --minify -o jsonpath='{..namespace}')}"
[[ -n "$NS" && "$NS" != default ]] || die "no project selected: run oc project <name>, or set FS_NAMESPACE"
kubectl auth can-i create deployments -n "$NS" >/dev/null \
  || die "you can't create deployments in $NS: is that your project, and are you logged in?"

# --- Which images --------------------------------------------------------------------------------
REGISTRY="${FS_IMAGE_REGISTRY:-}"
if [[ -z "$REGISTRY" ]]; then
  # https://github.com/Owner/repo(.git) or git@github.com:Owner/repo(.git) -> ghcr.io/owner
  owner=$(git -C "$ROOT" remote get-url origin | sed -E 's#^.*[:/]([^/]+)/[^/]+$#\1#')
  REGISTRY="ghcr.io/$(tr '[:upper:]' '[:lower:]' <<<"$owner")"
fi

if [[ -z "$TAG" ]]; then
  [[ -z "$(git -C "$ROOT" status --porcelain)" ]] \
    || die "uncommitted changes: images exist only for commits pushed to main. Commit and push first, or pass --tag"
  TAG=$(git -C "$ROOT" rev-parse HEAD | cut -c1-12)
  git -C "$ROOT" fetch --quiet origin main 2>/dev/null || true
  if ! git -C "$ROOT" merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
    echo "warning: $TAG is not on origin/main, so GitHub Actions may not have built its images" >&2
  fi
fi
echo "project $NS, images $REGISTRY/*:$TAG, database $PG_HOST"

# --- Manifests ------------------------------------------------------------------------------------
step "Rendering manifests"
render openshift "$NS" "$REGISTRY" "$TAG"

if ! apply_and_wait "$NS" deployment/api deployment/dagster-webserver deployment/dagster-daemon \
  deployment/web; then
  cat >&2 <<EOF

The rollout did not finish. Usual causes:
  - Pods stuck in Init: the database is unreachable. See
      kubectl -n $NS logs deploy/api -c wait-for-postgres
    and check the database's allowlist, POSTGRES_HOST/PORT and PGSSLMODE.
  - ImagePullBackOff: the images for $TAG don't exist (has the image workflow finished?) or the
    project can't pull them (infra/openshift.md, "Let the cluster pull the images").
  - FailedCreate / quota: kubectl -n $NS get events --sort-by=.lastTimestamp | tail -20
EOF
  exit 1
fi

print_access "$NS" "$TAG"
