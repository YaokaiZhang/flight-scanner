"""`python -m flight_scanner migrate|scan|rebuild|lakehouse|pack-raw|unblock <source>|
fail-orphaned-runs` - one-offs.

rebuild: re-parse every raw payload of the enabled sources and rebuild staging, history and marts.
lakehouse: run the daily lakehouse job now (export to Databricks, write its Baselines back;
    archive finished days of the raw store when FS_RAW_ARCHIVE is set).
pack-raw: move raw payloads stored one file each (before segments) into segments.
unblock: re-enable a source that disabled itself after being turned away (GET /sources/blocked).
fail-orphaned-runs: before the Dagster daemon starts, fail the runs a restart left in progress.
"""

import sys

from flight_scanner.config import Settings
from flight_scanner.db import migrate


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "migrate":
        print("applied:", migrate(Settings.from_env().db) or "nothing")
        return 0
    if cmd == "scan":
        from flight_scanner.pipeline import run_once
        from flight_scanner.pipeline.workspace import runtime_from_env

        runtime = runtime_from_env()
        migrate(runtime.db)
        return 0 if run_once(runtime).success else 1
    if cmd == "rebuild":
        from flight_scanner.pipeline import rebuild
        from flight_scanner.pipeline.workspace import runtime_from_env

        runtime = runtime_from_env()
        migrate(runtime.db)
        print(rebuild(runtime))
        return 0
    if cmd == "lakehouse":
        from flight_scanner.pipeline import run_lakehouse
        from flight_scanner.pipeline.workspace import runtime_from_env

        runtime = runtime_from_env()
        migrate(runtime.db)
        run = run_lakehouse(runtime)
        print(run or "off: set FS_LAKEHOUSE=databricks (see databricks/README.md)")
        return 0 if run is None or run.status != "failed" else 1
    if cmd == "pack-raw":
        from flight_scanner.db import connect
        from flight_scanner.raw_store import RawStore, pack_loose

        settings = Settings.from_env()
        migrate(settings.db)
        with connect(settings.db, autocommit=True) as conn:
            print("packed:", pack_loose(conn, RawStore(settings.raw_dir)))
        return 0
    if cmd == "unblock" and len(argv) == 3:
        from flight_scanner import source_health
        from flight_scanner.db import connect

        settings = Settings.from_env()
        migrate(settings.db)
        with connect(settings.db) as conn:
            done = source_health.unblock(conn, argv[2])
        print(f"{argv[2]}: {'re-enabled' if done else 'was not blocked'}")
        return 0
    if cmd == "fail-orphaned-runs":
        from dagster import DagsterInstance

        from flight_scanner.pipeline.orphans import fail_orphaned_runs

        with DagsterInstance.get() as instance:
            print("failed:", fail_orphaned_runs(instance) or "nothing")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
