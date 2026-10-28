from datetime import UTC, datetime

import pytest

from flight_scanner.testing.harness import PipelineHarness


@pytest.fixture
def pipeline(db, tmp_path, dbt_parse_dir) -> PipelineHarness:
    start = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    return PipelineHarness(db, tmp_path, start=start, dbt_parse_dir=dbt_parse_dir)
