from collections.abc import Iterator
from pathlib import Path

import pytest

from flight_scanner.db import DbSettings
from flight_scanner.testing.ephemeral_pg import EphemeralPostgres


@pytest.fixture(scope="session")
def postgres() -> Iterator[tuple[EphemeralPostgres, str]]:
    pg = EphemeralPostgres.start()
    try:
        template = pg.create_template()
        yield pg, template
    finally:
        pg.stop()


@pytest.fixture
def db(postgres) -> DbSettings:
    """A fresh, fully migrated database per test, always under the same name: dbt's parse
    depends on the database name, so tests can then share it (see `dbt_parse_dir`)."""
    pg, template = postgres
    return pg.clone(template, name="fs_test")


@pytest.fixture(scope="session")
def dbt_parse_dir(tmp_path_factory) -> Path:
    """dbt's parse state, shared by every test's pipeline: only the first build parses fully."""
    return tmp_path_factory.mktemp("dbt-parse")
