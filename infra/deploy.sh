#!/usr/bin/env bash
# Build the images in Azure and deploy the app to the AKS cluster made by infra/terraform.
#
#   infra/deploy.sh            build (if this commit isn't built yet) and deploy
#   infra/deploy.sh --no-build deploy the images of this commit without building
#
# Needs: az (logged in), kubectl, terraform, and an applied infra/terraform. Reads the app's
# settings and secrets from .env at the repo root, exactly like the Docker Compose stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/infra/terraform"
WORK="$ROOT/infra/k8s/.deploy" # generated overlay; git-ignored
ENV_FILE="${FS_ENV_FILE:-$ROOT/.env}"
BUILD=1
[[ "${1:-}" == "--no-build" ]] && BUILD=0

# shellcheck source=infra/lib.sh
source "$ROOT/infra/lib.sh"

need az kubectl terraform git
check_env_file

# --- What Terraform made ----------------------------------------------------------------------------
step "Reading Terraform outputs"
tf_out() { terraform -chdir="$TF_DIR" output -raw "$1"; }
RG=$(tf_out resource_group)
CLUSTER=$(tf_out cluster_name)
ACR=$(tf_out acr_name)
REGISTRY=$(tf_out acr_login_server)
NS=$(tf_out app_namespace)
echo "cluster $CLUSTER, registry $REGISTRY, namespace $NS"

# Merges the cluster's credentials into ~/.kube/config and makes it kubectl's current context.
az aks get-credentials --resource-group "$RG" --name "$CLUSTER" --overwrite-existing --only-show-errors

# --- Images ---------------------------------------------------------------------------------------
# Tagged with the git commit, so the cluster always runs an identifiable version, and a
# rollback is a redeploy of an older commit. Uncommitted changes get a unique tag of their own.
TAG=$(git -C "$ROOT" rev-parse --short=12 HEAD)
if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
  TAG="$TAG-dirty-$(date +%Y%m%d%H%M%S)"
fi

build() { # build <image> <dockerfile> <context>
  if az acr repository show --name "$ACR" --image "$1:$TAG" --only-show-errors >/dev/null 2>&1; then
    echo "$1:$TAG is already in the registry"
    return
  fi
  # `az acr build` uploads the context and builds in Azure: no local Docker needed.
  az acr build --registry "$ACR" --image "$1:$TAG" --file "$2" "$3" --only-show-errors
}

if ((BUILD)); then
  step "Building images ($TAG)"
  build flight-scanner-python "$ROOT/docker/python.Dockerfile" "$ROOT"
  build flight-scanner-web "$ROOT/web/Dockerfile" "$ROOT/web"
fi

# --- Manifests ------------------------------------------------------------------------------------
step "Rendering manifests"
render aks "$NS" "$REGISTRY" "$TAG"

# Postgres first: the other pods wait for it in their init containers.
apply_and_wait "$NS" statefulset/postgres deployment/api deployment/dagster-webserver \
  deployment/dagster-daemon deployment/web

print_access "$NS" "$TAG"
