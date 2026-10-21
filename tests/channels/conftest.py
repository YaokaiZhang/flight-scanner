from datetime import UTC, date, datetime

import pytest

from flight_scanner.notify.base import AlertMessage


@pytest.fixture
def round_trip_alert() -> AlertMessage:
    """A Verified two-ticket round trip judged against a route Baseline."""
    return AlertMessage(
        deal_id=7,
        watch_id=3,
        watch_name="Sun in November",
        origin="HEL",
        destination="HRG",
        outbound_date=date(2026, 11, 14),
        return_date=date(2026, 11, 19),
        adults=2,
        price_total_eur=236.0,
        price_per_adult_eur=118.0,
        verification="verified",
        baseline_tier="route",
        source="travelpayouts",
        observed_at=datetime(2026, 10, 21, 8, 38, tzinfo=UTC),
        booking_url="https://example.test/book?trip=HEL-HRG&a=1&b=2",
        airlines="airBaltic, Ryanair",
        stops=1,
        travel_minutes=925,
        ticketing="separate_tickets",
        separate_tickets=True,
        baseline_per_adult_eur=214.0,
        alert_id=41,
    )
