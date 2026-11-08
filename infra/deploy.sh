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

die() { echo "error: $*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

for cmd in az kubectl terraform git; do
  command -v "$cmd" >/dev/null || die "$cmd is not on PATH"
done

# --- .env checks ----------------------------------------------------------------------------------
[[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found: cp .env.example .env, then edit it"
if grep -qE '^POSTGRES_PASSWORD=(change-me)?$' "$ENV_FILE"; then
  die "set a real POSTGRES_PASSWORD in $ENV_FILE"
fi
# Kubernetes takes values literally, unlike Docker Compose: quotes and trailing comments
# would become part of the value.
if bad=$(grep -nE '^[A-Za-z_][A-Za-z0-9_]*=(["'"'"'].*|.*[[:space:]]#.*)$' "$ENV_FILE"); then
  die "remove the quotes or trailing comments on these lines of $ENV_FILE:
$bad"
fi

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
# A throwaway overlay on top of overlays/aks adds what is known only now: the image names, and
# the Secret made from .env. secretGenerator names the Secret after a hash of its contents
# (flight-scanner-env-<hash>) and rewrites every reference to it, so changing .env rolls the pods
# that read it. A plain Secret would change silently and pods would keep the old values.
step "Rendering manifests"
rm -rf "$WORK"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT
cp "$ENV_FILE" "$WORK/app.env"
cat >"$WORK/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../overlays/aks
images:
  - name: flight-scanner-python
    newName: $REGISTRY/flight-scanner-python
    newTag: "$TAG"
  - name: flight-scanner-web
    newName: $REGISTRY/flight-scanner-web
    newTag: "$TAG"
secretGenerator:
  - name: flight-scanner-env
    namespace: $NS
    envs: [app.env]
    options:
      labels:
        flight-scanner/env: "true"
EOF
kubectl kustomize "$WORK" >"$WORK/rendered.yaml"
SECRET=$(awk '/^kind: Secret/{s=1} s && /^  name: /{print $2; exit}' "$WORK/rendered.yaml")

step "Applying"
# apply is declarative: Kubernetes compares what you send with what exists and changes only the
# difference. Running it twice in a row changes nothing the second time.
kubectl apply -f "$WORK/rendered.yaml"

step "Waiting for the rollout"
# Postgres first: the other pods wait for it in their init containers.
kubectl -n "$NS" rollout status statefulset/postgres --timeout=10m
for d in api dagster-webserver dagster-daemon web; do
  kubectl -n "$NS" rollout status "deployment/$d" --timeout=10m
done

# Secrets made by earlier deploys are no longer referenced by anything.
kubectl -n "$NS" get secret -l flight-scanner/env=true -o name \
  | grep -v "secret/$SECRET\$" | xargs -r kubectl -n "$NS" delete

cat <<EOF

Deployed $TAG. Nothing is public; reach the UIs through port forwards:

  kubectl -n $NS port-forward svc/web 3000:3000                 # UI   -> http://127.0.0.1:3000
  kubectl -n $NS port-forward svc/dagster-webserver 3001:3001   # Dagster -> http://127.0.0.1:3001

Run a scan now:  kubectl -n $NS exec deploy/dagster-daemon -- python -m flight_scanner scan
EOF
