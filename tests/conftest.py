from collections.abc import Iterator

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
    """A fresh, fully migrated database per test."""
    pg, template = postgres
    return pg.clone(template)
