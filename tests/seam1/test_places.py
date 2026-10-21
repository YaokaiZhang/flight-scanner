"""Seam 1: Place resolution with Exclusions, end to end (fake source in -> Alerts out)."""

import csv
import shutil

from flight_scanner.places import DATA_DIR, ReferenceData


def fare(origin: str, destination: str, price: float, day: str = "2026-11-14") -> dict:
    return {
        "currency": "EUR",
        "prices": [
            {"origin": origin, "destination": destination, "depart_date": day, "price": price}
        ],
    }


def watch(origins: dict, destinations: dict, threshold_eur: float = 100) -> dict:
    return {
        "name": "Places",
        "origins": origins,
        "destinations": destinations,
        "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
        "price_threshold": {"amount_eur": threshold_eur, "basis": "total"},
    }


HEL = {"include": [{"kind": "airport", "code": "HEL"}]}


def routes(pipeline) -> set[tuple[str, str]]:
    return {(a.origin, a.destination) for a in pipeline.notifier.alerts}


def test_europe_excluding_sweden_alerts_for_barcelona_but_not_stockholm(pipeline):
    pipeline.create_watch(
        watch(
            HEL,
            {
                "include": [{"kind": "region", "code": "europe"}],
                "exclude": [{"kind": "country", "code": "SE"}],
            },
        )
    )
    pipeline.fake.replay(fare("HEL", "ARN", 39), route=("HEL", "ARN"))
    pipeline.fake.replay(fare("HEL", "BCN", 59), route=("HEL", "BCN"))

    pipeline.run()

    assert routes(pipeline) == {("HEL", "BCN")}


def test_exclusions_work_on_the_origin_side(pipeline):
    pipeline.create_watch(
        watch(
            {
                "include": [{"kind": "country", "code": "FI"}],
                "exclude": [{"kind": "airport", "code": "HEL"}],
            },
            {"include": [{"kind": "airport", "code": "BCN"}]},
        )
    )
    pipeline.fake.replay(fare("HEL", "BCN", 59), route=("HEL", "BCN"))
    pipeline.fake.replay(fare("TMP", "BCN", 69), route=("TMP", "BCN"))

    pipeline.run()

    assert routes(pipeline) == {("TMP", "BCN")}


def test_resolved_airports_follow_reference_data_changes(pipeline, tmp_path):
    """A Watch for Spain picks up an airport added to the reference data without being edited."""
    pipeline.create_watch(watch(HEL, {"include": [{"kind": "country", "code": "ES"}]}))
    pipeline.fake.replay(fare("HEL", "XNW", 49), route=("HEL", "XNW"))

    pipeline.run()
    assert pipeline.notifier.alerts == []  # XNW is not a known Spanish airport yet

    updated = tmp_path / "reference"
    shutil.copytree(DATA_DIR, updated)
    with open(updated / "airports.csv", "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\n").writerow(
            ["XNW", "New Airport", "medium_airport", "", "ES", "40.0", "-3.0"]
        )
    pipeline.use_reference(ReferenceData.load(updated))
    pipeline.clock.advance(minutes=30)
    pipeline.run()

    assert routes(pipeline) == {("HEL", "XNW")}
