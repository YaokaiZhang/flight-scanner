"""Places: what a Watch names as origin or destination, and their resolution to airports.

Walking skeleton: only airport Places exist, and an airport resolves to itself. Ticket 03 adds
cities, countries and Regions from reference data behind this same `resolve` interface.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlaceRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["airport"]
    code: str = Field(pattern=r"^[A-Z]{3}$")


class PlaceSet(BaseModel):
    """Places to include, minus Exclusions."""

    include: list[PlaceRef] = Field(min_length=1)
    exclude: list[PlaceRef] = Field(default_factory=list)


def resolve(places: PlaceSet) -> frozenset[str]:
    """Resolve `include − exclude` to a set of IATA airport codes."""
    included = {p.code for p in places.include}
    excluded = {p.code for p in places.exclude}
    return frozenset(included - excluded)
