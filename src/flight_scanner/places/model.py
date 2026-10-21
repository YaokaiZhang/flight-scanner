"""Place shapes: what Watches store and what the API returns."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PlaceKind = Literal["airport", "city", "country", "region"]

_CODE_PATTERNS = {
    "airport": r"^[A-Z]{3}$",
    "city": r"^[A-Z]{2}(-[A-Z0-9]{1,3})?-[a-z0-9-]+$",
    "country": r"^[A-Z]{2}$",
    "region": r"^[a-z][a-z0-9_]*$",
}


class PlaceRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: PlaceKind
    code: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _code_matches_kind(self) -> PlaceRef:
        if not re.match(_CODE_PATTERNS[self.kind], self.code):
            raise ValueError(f"{self.code!r} is not a valid {self.kind} code")
        return self


class PlaceSet(BaseModel):
    """Places to include, minus Exclusions."""

    include: list[PlaceRef] = Field(min_length=1)
    exclude: list[PlaceRef] = Field(default_factory=list)


class Place(BaseModel):
    kind: PlaceKind
    code: str
    name: str
    context: str | None = None  # e.g. "Barcelona, Spain" for an airport
    airport_count: int


class TreeNode(Place):
    via: str | None = None  # territory included through its sovereign country (its name)
    children: list[TreeNode] | None = None  # None: not expanded (depth limit) or a leaf airport
