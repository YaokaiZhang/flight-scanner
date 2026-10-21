#!/usr/bin/env bash
# Run the Python test suite on a CSC Roihu compute node (Slurm), not the shared login node.
#
#   scripts/test-slurm.sh                      # whole suite: pytest tests -n $CPUS
#   scripts/test-slurm.sh tests/seam1 -x       # any pytest arguments
#   CPUS=32 PARTITION=gpumedium TIME=30 scripts/test-slurm.sh
#
# GPU partitions only: the login node and GPU nodes are aarch64 (GH200) like the `flight-scanner`
# conda env, while the CPU partitions (test, small, ...) are x86_64 nodes that cannot run it. GPU
# partitions require a GPU, so the job takes one GH200 slice (the tests do not use it).
#
# Blocks until the job ends and prints pytest's output; exits with pytest's status.
# Everything temporary (ephemeral Postgres, pytest tmp dirs, dbt targets) lives on the node's
# local /tmp. A `.venv` or `dbt/target` symlinked into the login node's /tmp (see CONVENTIONS)
# does not exist on the compute node, so the job recreates it there (uv sync, ~1 min) and
# removes it afterwards.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACCOUNT="${ACCOUNT:-project_2020551}"
PARTITION="${PARTITION:-gputest}"  # max 15 min, usually starts at once; else gpumedium
TIME="${TIME:-15}"               # minutes
CPUS="${CPUS:-16}"
WORKERS="${WORKERS:-$CPUS}"      # pytest-xdist workers
CONDA_SH="${CONDA_SH:-/scratch/project_2020551/miniconda3/etc/profile.d/conda.sh}"

exec srun --account="$ACCOUNT" --partition="$PARTITION" --time="$TIME" \
    --nodes=1 --ntasks=1 --cpus-per-task="$CPUS" --mem-per-cpu=2G --gres=gpu:gh200:1 \
    --job-name=fs-tests --chdir="$ROOT" \
    bash -s -- "$CONDA_SH" "$WORKERS" "$@" <<'JOB'
set -eo pipefail
conda_sh="$1"; workers="$2"; shift 2
source "$conda_sh"
conda activate flight-scanner  # (conda's scripts are not `set -u` clean)
set -u
export TMPDIR="/tmp/${USER}-fs-tests-${SLURM_JOB_ID}"
export FS_PG_TMP="$TMPDIR"
mkdir -p "$TMPDIR"
made=("$TMPDIR")
cleanup() { rm -rf "${made[@]}"; }
trap cleanup EXIT

# symlinks into the login node's /tmp resolve to this node's /tmp: create what they point at
if [ -L dbt/target ] && [ ! -e dbt/target ]; then
    mkdir -p "$(readlink dbt/target)"; made+=("$(readlink dbt/target)")
fi
if [ -L .venv ] && [ ! -e .venv ]; then
    venv="$(readlink .venv)"; made+=("$venv")
    UV_PROJECT_ENVIRONMENT="$venv" UV_LINK_MODE=copy uv sync --frozen --quiet --python "$(command -v python)"
fi

echo "$(hostname): pytest -n $workers on $(nproc) CPUs"
start=$SECONDS
status=0
.venv/bin/pytest -n "$workers" -p no:cacheprovider --basetemp="$TMPDIR/pytest" "${@:-tests}" || status=$?
echo "pytest wall time: $((SECONDS - start)) s"
exit $status
JOB
