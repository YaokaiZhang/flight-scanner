"""Seam 2: a restart fails the runs it orphaned, so they stop holding the only run slot."""

from dagster import DagsterInstance, DagsterRun, DagsterRunStatus

from flight_scanner.pipeline.orphans import fail_orphaned_runs


def test_in_progress_runs_fail_and_finished_runs_stay():
    with DagsterInstance.ephemeral() as instance:
        for run_id, status in [
            ("started", DagsterRunStatus.STARTED),
            ("done", DagsterRunStatus.SUCCESS),
        ]:
            instance.add_run(DagsterRun(job_name="scan", run_id=run_id, status=status))

        assert fail_orphaned_runs(instance) == ["started"]

        status = {r.run_id: r.status for r in instance.get_runs()}
        assert status == {
            "started": DagsterRunStatus.FAILURE,
            "done": DagsterRunStatus.SUCCESS,
        }
