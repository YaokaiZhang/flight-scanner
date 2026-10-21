from datetime import UTC, datetime

import pytest

from flight_scanner.testing.harness import PipelineHarness


@pytest.fixture
def pipeline(db, tmp_path) -> PipelineHarness:
    return PipelineHarness(db, tmp_path, start=datetime(2026, 10, 21, 9, 0, tzinfo=UTC))
