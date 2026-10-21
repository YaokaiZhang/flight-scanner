"""Compile the dbt project for Databricks without a workspace (ADR-0003 portability check).

    sql = compile_for_databricks(work_dir, as_of)   # {model name: compiled SQL}

`dbt compile --target databricks` normally needs a live SQL warehouse even for models that
never introspect: dbt-databricks asks the connection which runtime capabilities it has (for
dateadd/datediff and incremental strategies) and whether an incremental model's table exists.
This runs dbt in a child process with those two questions answered offline (every capability
of a current serverless SQL warehouse; no table exists yet, so incremental models compile as
their first build). Nothing connects to Databricks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from flight_scanner.pipeline import dbt as dbt_files

PROFILE = """flight_scanner:
  target: databricks
  outputs:
    databricks:
      type: databricks
      catalog: flight_scanner
      schema: silver
      host: offline.cloud.databricks.com
      http_path: /sql/1.0/warehouses/offline
      token: offline
      threads: 1
"""


def compile_for_databricks(work_dir: Path, as_of: datetime) -> dict[str, str]:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "profiles.yml").write_text(PROFILE)
    target = work_dir / "target"
    env = {
        **os.environ,
        dbt_files.AS_OF_ENV: as_of.isoformat(),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
    }
    subprocess.run(
        [sys.executable, "-m", __name__, str(work_dir), str(target)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    manifest = json.loads((target / "manifest.json").read_text())
    return {
        n["name"]: n["compiled_code"]
        for n in manifest["nodes"].values()
        if n["resource_type"] == "model"
    }


def _main(profiles_dir: str, target: str) -> int:
    from dbt.adapters.databricks.impl import DatabricksAdapter
    from dbt.cli.main import dbtRunner

    DatabricksAdapter.has_capability = lambda self, capability: True
    DatabricksAdapter.get_relation = lambda self, *args, **kwargs: None
    result = dbtRunner().invoke(
        [
            "compile",
            "--quiet",
            "--project-dir",
            str(dbt_files.DBT_PROJECT_DIR),
            "--profiles-dir",
            profiles_dir,
            "--target-path",
            target,
            "--no-introspect",
            "--no-populate-cache",
            "--no-partial-parse",
        ]
    )
    if not result.success:
        print(result.exception, file=sys.stderr)
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1], sys.argv[2]))
