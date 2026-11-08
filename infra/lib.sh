# shellcheck shell=bash
# Shared by infra/deploy.sh (AKS) and infra/deploy-openshift.sh. Sourced, not run.
# The callers set ROOT, ENV_FILE and WORK before using these.

die() { echo "error: $*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

need() { # need <command>...
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null || die "$cmd is not on PATH"
  done
}

check_env_file() {
  [[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found: cp .env.example .env, then edit it"
  if grep -qE '^POSTGRES_PASSWORD=(change-me)?$' "$ENV_FILE"; then
    die "set a real POSTGRES_PASSWORD in $ENV_FILE"
  fi
  # Kubernetes takes values literally, unlike Docker Compose: quotes and trailing comments
  # would become part of the value.
  local bad
  if bad=$(grep -nE '^[A-Za-z_][A-Za-z0-9_]*=(["'"'"'].*|.*[[:space:]]#.*)$' "$ENV_FILE"); then
    die "remove the quotes or trailing comments on these lines of $ENV_FILE:
$bad"
  fi
}

env_value() { # env_value <NAME>: the last value of NAME in .env, empty if unset
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1
}

# render <overlay> <namespace> <registry> <tag>
#
# Writes a throwaway overlay on top of infra/k8s/overlays/<overlay> with what is known only at
# deploy time: the namespace, the image names, and the Secret made from .env. secretGenerator
# names the Secret after a hash of its contents (flight-scanner-env-<hash>) and rewrites every
# reference to it, so changing .env rolls the pods that read it. A plain Secret would change
# silently and pods would keep the old values. Sets RENDERED (the manifests) and SECRET (the
# Secret's generated name).
render() {
  local overlay=$1 ns=$2 registry=$3 tag=$4
  rm -rf "$WORK"
  mkdir -p "$WORK"
  trap 'rm -rf "$WORK"' EXIT
  cp "$ENV_FILE" "$WORK/app.env"
  cat >"$WORK/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../overlays/$overlay
namespace: $ns
images:
  - name: flight-scanner-python
    newName: $registry/flight-scanner-python
    newTag: "$tag"
  - name: flight-scanner-web
    newName: $registry/flight-scanner-web
    newTag: "$tag"
secretGenerator:
  - name: flight-scanner-env
    envs: [app.env]
    options:
      labels:
        flight-scanner/env: "true"
EOF
  RENDERED="$WORK/rendered.yaml"
  kubectl kustomize "$WORK" >"$RENDERED"
  SECRET=$(awk '/^kind: Secret/{s=1} s && /^  name: /{print $2; exit}' "$RENDERED")
}

# apply_and_wait <namespace> <workload>...: apply RENDERED, wait for each workload in order,
# then delete the Secrets of earlier deploys, which nothing references any more. Returns 1 if
# the apply or a rollout fails, so callers can add hints (errexit is off in `f || ...`).
apply_and_wait() {
  local ns=$1 w
  shift
  step "Applying"
  # apply is declarative: Kubernetes compares what you send with what exists and changes only
  # the difference. Running it twice in a row changes nothing the second time.
  kubectl apply -f "$RENDERED" || return 1

  step "Waiting for the rollout"
  for w in "$@"; do
    kubectl -n "$ns" rollout status "$w" --timeout=10m || return 1
  done

  # `|| true`: grep exits 1 when there is nothing to delete, as on the first deploy.
  kubectl -n "$ns" get secret -l flight-scanner/env=true -o name \
    | { grep -v "secret/$SECRET\$" || true; } | xargs -r kubectl -n "$ns" delete
}

print_access() { # print_access <namespace> <tag>
  cat <<EOF

Deployed $2. Nothing is public; reach the UIs through port forwards:

  kubectl -n $1 port-forward svc/web 3000:3000                 # UI   -> http://127.0.0.1:3000
  kubectl -n $1 port-forward svc/dagster-webserver 3001:3001   # Dagster -> http://127.0.0.1:3001

Run a scan now:  kubectl -n $1 exec deploy/dagster-daemon -- python -m flight_scanner scan
EOF
}
