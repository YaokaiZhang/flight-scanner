"""Postgres connection settings and schema migrations.

Migrations are plain SQL files in `flight_scanner/migrations/`, applied in filename order and
recorded in `public.schema_migrations`. Add a new file `NNNN_<what>.sql`; never edit an applied one.
Tables owned by Python code live in schemas `app` (Watches, Deals, Alerts) and `landing`
(parsed source rows + the raw-payload manifest). dbt owns `staging` and `marts`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row


@dataclass(frozen=True)
class DbSettings:
    host: str
    port: int
    user: str
    password: str
    dbname: str

    @property
    def conninfo(self) -> str:
        return make_conninfo(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password or None,
            dbname=self.dbname,
        )

    @classmethod
    def from_env(cls, env: os._Environ | dict | None = None) -> DbSettings:
        env = os.environ if env is None else env
        return cls(
            host=env.get("POSTGRES_HOST", "localhost"),
            port=int(env.get("POSTGRES_PORT", "5432")),
            user=env.get("POSTGRES_USER", "flightscanner"),
            password=env.get("POSTGRES_PASSWORD", ""),
            dbname=env.get("POSTGRES_DB", "flightscanner"),
        )


def connect(settings: DbSettings, **kwargs) -> psycopg.Connection:
    return psycopg.connect(settings.conninfo, row_factory=dict_row, **kwargs)


def migrate(settings: DbSettings) -> list[str]:
    """Apply pending migrations; returns the names applied."""
    files = sorted(
        (
            f
            for f in resources.files("flight_scanner.migrations").iterdir()
            if f.name.endswith(".sql")
        ),
        key=lambda f: f.name,
    )
    applied: list[str] = []
    with connect(settings) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(727274)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r["name"] for r in conn.execute("SELECT name FROM public.schema_migrations")}
        for f in files:
            if f.name in done:
                continue
            conn.execute(f.read_text())
            conn.execute("INSERT INTO public.schema_migrations (name) VALUES (%s)", (f.name,))
            applied.append(f.name)
    return applied
