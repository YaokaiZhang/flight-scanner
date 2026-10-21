"""An ephemeral PostgreSQL server: initdb into a temp dir, listen only on a unix socket there.

Parallel worktrees and test sessions never collide because nothing listens on TCP.
Requires `initdb` and `pg_ctl` on PATH (the `flight-scanner` conda env provides them).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg

from flight_scanner.db import DbSettings, migrate


@dataclass
class EphemeralPostgres:
    root: Path
    port: int = 5432  # only names the socket file; no TCP listener

    @property
    def socket_dir(self) -> Path:
        return self.root / "sock"

    def settings(self, dbname: str = "postgres") -> DbSettings:
        return DbSettings(
            host=str(self.socket_dir), port=self.port, user="postgres", password="", dbname=dbname
        )

    @classmethod
    def start(cls, root: Path | None = None) -> EphemeralPostgres:
        # unix socket paths are limited to ~107 bytes, so keep the root short
        root = Path(
            root or tempfile.mkdtemp(prefix="fspg-", dir=os.environ.get("FS_PG_TMP", "/tmp"))
        )
        pg = cls(root=root)
        data = root / "data"
        pg.socket_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "initdb",
                "-D",
                str(data),
                "-U",
                "postgres",
                "--auth=trust",
                "-E",
                "UTF8",
                "--locale=C",
                "--no-sync",
            ],
            check=True,
            capture_output=True,
        )
        opts = (
            f"-c listen_addresses='' -c unix_socket_directories='{pg.socket_dir}' "
            f"-c port={pg.port} -c fsync=off -c synchronous_commit=off -c full_page_writes=off "
            "-c max_connections=200 -c shared_buffers=32MB"
        )
        subprocess.run(
            ["pg_ctl", "-D", str(data), "-o", opts, "-l", str(root / "pg.log"), "-w", "start"],
            check=True,
            capture_output=True,
        )
        return pg

    def stop(self) -> None:
        subprocess.run(
            ["pg_ctl", "-D", str(self.root / "data"), "-m", "immediate", "-w", "stop"],
            capture_output=True,
        )
        shutil.rmtree(self.root, ignore_errors=True)

    def create_template(self, name: str = "fs_template") -> str:
        """Create a fully migrated database to clone per test."""
        self._admin(f'CREATE DATABASE "{name}"')
        migrate(self.settings(name))
        return name

    def clone(self, template: str) -> DbSettings:
        name = f"t_{uuid.uuid4().hex[:12]}"
        self._admin(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
        return self.settings(name)

    def _admin(self, sql: str) -> None:
        with psycopg.connect(self.settings().conninfo, autocommit=True) as conn:
            conn.execute(sql)
