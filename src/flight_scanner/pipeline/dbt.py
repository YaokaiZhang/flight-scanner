"""dbt plumbing: where the project is, keeping its manifest fresh, and per-database profiles."""

from __future__ import annotations

import fcntl
import functools
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dagster_dbt import DbtCliResource
from packaging import version

from flight_scanner.db import DbSettings

if TYPE_CHECKING:
    import dagster as dg

    from flight_scanner.pipeline.runtime import Runtime

DBT_PROJECT_DIR = Path(
    os.environ.get("FS_DBT_PROJECT_DIR", Path(__file__).resolve().parents[3] / "dbt")
)
PROFILE = "flight_scanner"
AS_OF_ENV = "FS_AS_OF"  # the injected clock's instant, read by the `as_of()` macro
PARTIAL_PARSE = "partial_parse.msgpack"
_env_lock = threading.Lock()


def dbt_executable() -> str:
    """The dbt next to this interpreter (the venv's), so PATH does not matter."""
    return str(Path(sys.executable).with_name("dbt"))


class DbtCli(DbtCliResource):
    """`DbtCliResource` that asks the dbt executable for its version once per process instead of
    once per resource instance, i.e. per scan (`dbt --version` takes 1-2 s)."""

    @functools.cached_property
    def _cli_version(self) -> version.Version:
        return _cli_version(self.dbt_executable)


@functools.cache
def _cli_version(executable: str) -> version.Version:
    out = subprocess.run([executable, "--version"], check=True, capture_output=True, text=True)
    match = re.search(r"(\d+\.\d+\.\d+)", out.stdout)
    if not match:
        raise ValueError(f"Could not parse dbt version from: {out.stdout}")
    return version.parse(match.group(1))


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


def build(
    context: dg.AssetExecutionContext, dbt: DbtCliResource, runtime: Runtime
) -> Iterator[Any]:
    """`dbt build` of the asset's selection at the clock's instant, streaming Dagster events.

    Consecutive builds reuse dbt's parse (see `clock_env`, `new_target_path`); dbt's data tests
    run unless `runtime.dbt_data_tests` is off (seam-1 harness only)."""
    args = ["build"]
    if not runtime.dbt_data_tests:
        args += ["--exclude-resource-type", "test", "--exclude-resource-type", "unit_test"]
    target = new_target_path(runtime.work_dir)
    with clock_env(runtime.clock.now()):
        invocation = dbt.cli(args, context=context, target_path=target)
    yield from invocation.stream()
    finish_target_path(target)


@contextmanager
def clock_env(as_of: datetime) -> Iterator[None]:
    """Expose the clock instant to dbt as `FS_AS_OF` (read by the `as_of()` macro) while a dbt
    process is started. An env var, not `--vars`: changing vars forces dbt to re-parse the whole
    project, and the macro reads it only at execution so the parse never depends on it."""
    with _env_lock:
        before = os.environ.get(AS_OF_ENV)
        os.environ[AS_OF_ENV] = as_of.isoformat()
        try:
            yield
        finally:
            if before is None:
                os.environ.pop(AS_OF_ENV, None)
            else:
                os.environ[AS_OF_ENV] = before


def new_target_path(work_dir: Path) -> Path:
    """A fresh dbt target dir for one invocation, seeded with the last saved parse state so dbt
    partially parses (nothing changed: no parsing) instead of parsing the whole project."""
    root = work_dir / "dbt-target"
    target = root / uuid.uuid4().hex[:12]
    target.mkdir(parents=True)
    saved = root / PARTIAL_PARSE
    if saved.exists():
        shutil.copy(saved, target / PARTIAL_PARSE)
    return target


def finish_target_path(target: Path) -> None:
    """Keep the invocation's parse state for the next one and drop its other artifacts."""
    state = target / PARTIAL_PARSE
    if state.exists():
        tmp = target.parent / f".{target.name}.{PARTIAL_PARSE}"
        shutil.copy(state, tmp)
        tmp.replace(target.parent / PARTIAL_PARSE)  # atomic for concurrent invocations
    shutil.rmtree(target, ignore_errors=True)


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
