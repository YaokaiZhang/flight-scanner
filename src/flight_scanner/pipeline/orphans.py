"""Runs a restart left behind. Run workers die with the Dagster daemon but stay "in progress" in its
storage, holding the only run slot, and the default run launcher cannot tell that a worker is dead.
Only call this while the daemon is down: then no in-progress run can really be running.

  fail_orphaned_runs(instance) -> run ids failed
"""

from __future__ import annotations

from dagster import DagsterInstance, RunsFilter
from dagster._core.storage.dagster_run import IN_PROGRESS_RUN_STATUSES


def fail_orphaned_runs(instance: DagsterInstance) -> list[str]:
    runs = instance.get_runs(RunsFilter(statuses=IN_PROGRESS_RUN_STATUSES))
    for run in runs:
        instance.report_run_failed(run, "Its worker was lost when the Dagster daemon stopped.")
    return [run.run_id for run in runs]
