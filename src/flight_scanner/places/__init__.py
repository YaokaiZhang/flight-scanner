"""Places: what a Watch names as origin or destination, and their resolution to airports.

A Place is an airport, a city, a country or a Region; every Place resolves to a set of airports.
Watches store Place references (kind + code), never resolved airports, so a Watch picks up new or
changed reference data on the next resolution.

Interface:
  PlaceRef / PlaceSet          - what Watches store (include − exclude)
  ReferenceData                - loaded reference data; `default_reference()` is the bundled one
    .search(q, limit)          - Places by name or code, best first
    .resolve(place_set)        - IATA airport codes of include − exclude
    .unknown(place_set)        - references the data does not know
    .describe(ref) / .tree(ref, depth) / .regions()
  Place / TreeNode             - API shapes

Reference data lives in `places/data/`: a trimmed OurAirports snapshot (rebuilt by
`python -m flight_scanner.places.refresh`) and the hand-written `regions.toml`.
"""

from __future__ import annotations

from flight_scanner.places.model import Place, PlaceKind, PlaceRef, PlaceSet, TreeNode
from flight_scanner.places.reference import DATA_DIR, ReferenceData, default_reference


def resolve(places: PlaceSet, reference: ReferenceData | None = None) -> frozenset[str]:
    """Resolve `include − exclude` to IATA airport codes. Unknown Places resolve to nothing."""
    return (reference or default_reference()).resolve(places)


__all__ = [
    "DATA_DIR",
    "Place",
    "PlaceKind",
    "PlaceRef",
    "PlaceSet",
    "ReferenceData",
    "TreeNode",
    "default_reference",
    "resolve",
]
