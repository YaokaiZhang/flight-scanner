"""dbt plumbing: where the project is, keeping its manifest fresh, and per-database profiles."""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from pathlib import Path

from flight_scanner.db import DbSettings

DBT_PROJECT_DIR = Path(
    os.environ.get("FS_DBT_PROJECT_DIR", Path(__file__).resolve().parents[3] / "dbt")
)
PROFILE = "flight_scanner"


def dbt_executable() -> str:
    """The dbt next to this interpreter (the venv's), so PATH does not matter."""
    return str(Path(sys.executable).with_name("dbt"))


def manifest_path() -> Path:
    return DBT_PROJECT_DIR / "target" / "manifest.json"


def _newest_source_mtime() -> float:
    newest = 0.0
    for sub in ("models", "macros", "tests", "seeds", "snapshots"):
        for p in (DBT_PROJECT_DIR / sub).rglob("*"):
            if p.is_file():
                newest = max(newest, p.stat().st_mtime)
    return max(newest, (DBT_PROJECT_DIR / "dbt_project.yml").stat().st_mtime)


def ensure_manifest() -> Path:
    """Run `dbt parse` if the manifest is missing or older than any project file."""
    target = manifest_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target.parent / ".parse.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists() and target.stat().st_mtime >= _newest_source_mtime():
            return target
        subprocess.run(
            [
                dbt_executable(),
                "parse",
                "--quiet",
                "--project-dir",
                str(DBT_PROJECT_DIR),
                "--profiles-dir",
                str(DBT_PROJECT_DIR),
                "--target-path",
                "target",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return target


def write_profiles(db: DbSettings, directory: Path, threads: int = 4) -> Path:
    """A profiles.yml pointing dbt at exactly this database (so tests never share one)."""
    directory.mkdir(parents=True, exist_ok=True)

    def q(s: object) -> str:
        return "'" + str(s).replace("'", "''") + "'"

    (directory / "profiles.yml").write_text(
        f"""{PROFILE}:
  target: postgres
  outputs:
    postgres:
      type: postgres
      host: {q(db.host)}
      port: {db.port}
      user: {q(db.user)}
      password: {q(db.password)}
      dbname: {q(db.dbname)}
      schema: staging
      threads: {threads}
"""
    )
    return directory
