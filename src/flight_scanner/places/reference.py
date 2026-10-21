"""Reference data: airports, cities, countries and Regions, loaded from `places/data/`.

`ReferenceData.load(dir)` reads a snapshot directory (see `refresh.py` for the CSV shapes and
`data/regions.toml` for the Region rules) into memory; it is small (a few thousand airports), so
search and resolution are plain in-memory scans. Loading validates the Region file and fails loudly
on unknown country codes or sub-Regions that do not cover their parent.
"""

from __future__ import annotations

import csv
import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from flight_scanner.places.model import Place, PlaceRef, PlaceSet, TreeNode

DATA_DIR = Path(__file__).parent / "data"

_KIND_ORDER = {"region": 0, "country": 1, "city": 2, "airport": 3}
_AIRPORT_TYPE_ORDER = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}


def _fold(text: str) -> str:
    """Case- and accent-insensitive form used for matching."""
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.split(r"[^a-z0-9]+", ascii_.lower())).strip()


@dataclass(frozen=True)
class _Airport:
    code: str
    name: str
    type: str
    city: str | None
    country: str


@dataclass(frozen=True)
class _Region:
    code: str
    name: str
    countries: frozenset[str]
    via: dict[str, str]  # territory -> sovereign, for members included only through the sovereign
    children: tuple[str, ...]


@dataclass(frozen=True)
class _Entry:
    """One searchable Place."""

    kind: str
    code: str
    folded_code: str
    folded_name: str
    words: tuple[str, ...]
    extra: str  # folded city name for airports: "london" finds LHR
    order: tuple


@dataclass
class ReferenceData:
    version: str
    countries: dict[str, tuple[str, str]]  # code -> (name, continent)
    sovereign: dict[str, str]  # territory -> sovereign country
    cities: dict[str, tuple[str, str]]  # id -> (name, country)
    airports: dict[str, _Airport]
    regions: dict[str, _Region]
    _by_country: dict[str, set[str]] = field(default_factory=dict, repr=False)
    _by_city: dict[str, set[str]] = field(default_factory=dict, repr=False)
    _entries: list[_Entry] = field(default_factory=list, repr=False)

    # --- loading -------------------------------------------------------------------------------
    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> ReferenceData:
        data_dir = Path(data_dir)
        countries = {
            r["code"]: (r["name"], r["continent"]) for r in _rows(data_dir / "countries.csv")
        }
        cities = {r["id"]: (r["name"], r["country"]) for r in _rows(data_dir / "cities.csv")}
        airports = {
            r["iata"]: _Airport(r["iata"], r["name"], r["type"], r["city"] or None, r["country"])
            for r in _rows(data_dir / "airports.csv")
        }
        snapshot = tomllib.loads((data_dir / "snapshot.toml").read_text())
        spec = tomllib.loads((data_dir / "regions.toml").read_text())
        sovereign, regions = _regions(spec, countries)
        ref = cls(
            version=f"{snapshot['version']}+regions-{spec['version']}",
            countries=countries,
            sovereign=sovereign,
            cities=cities,
            airports=airports,
            regions=regions,
        )
        ref._index()
        return ref

    def _index(self) -> None:
        for a in self.airports.values():
            self._by_country.setdefault(a.country, set()).add(a.code)
            if a.city:
                self._by_city.setdefault(a.city, set()).add(a.code)
        for kind, code in self._all_refs():
            place = self._place(kind, code)
            extra = ""
            order: tuple = (-place.airport_count,)
            if kind == "airport":
                a = self.airports[code]
                extra = _fold(self.cities[a.city][0]) if a.city else ""
                order = (_AIRPORT_TYPE_ORDER.get(a.type, 9),)
            folded = _fold(place.name)
            self._entries.append(
                _Entry(kind, code, code.lower(), folded, tuple(folded.split()), extra, order)
            )

    def _all_refs(self):
        yield from (("region", c) for c in self.regions)
        yield from (("country", c) for c in self.countries)
        yield from (("city", c) for c in self.cities)
        yield from (("airport", c) for c in self.airports)

    # --- queries -------------------------------------------------------------------------------
    def airports_of(self, ref: PlaceRef) -> frozenset[str]:
        """Airports a single Place resolves to; empty when the Place is unknown."""
        match ref.kind:
            case "airport":
                return frozenset({ref.code}) if ref.code in self.airports else frozenset()
            case "city":
                return frozenset(self._by_city.get(ref.code, ()))
            case "country":
                return frozenset(self._by_country.get(ref.code, ()))
            case "region":
                region = self.regions.get(ref.code)
                if region is None:
                    return frozenset()
                return frozenset().union(*(self._by_country.get(c, ()) for c in region.countries))
        return frozenset()

    def resolve(self, places: PlaceSet) -> frozenset[str]:
        """IATA codes of `include − exclude`. Unknown Places resolve to nothing."""
        included = frozenset().union(*(self.airports_of(p) for p in places.include))
        excluded = frozenset().union(*(self.airports_of(p) for p in places.exclude))
        return included - excluded

    def known(self, ref: PlaceRef) -> bool:
        table = {
            "airport": self.airports,
            "city": self.cities,
            "country": self.countries,
            "region": self.regions,
        }[ref.kind]
        return ref.code in table

    def unknown(self, places: PlaceSet) -> list[PlaceRef]:
        return [p for p in [*places.include, *places.exclude] if not self.known(p)]

    def describe(self, ref: PlaceRef) -> Place | None:
        return self._place(ref.kind, ref.code) if self.known(ref) else None

    def regions_list(self) -> list[Place]:
        return [self._place("region", c) for c in self.regions]

    def search(self, query: str, limit: int = 10) -> list[Place]:
        q = _fold(query)
        if not q:
            return []
        scored = []
        for e in self._entries:
            if e.folded_code == q.replace(" ", ""):
                rank = 0
            elif e.folded_name.startswith(q):
                rank = 1
            elif any(w.startswith(q) for w in e.words) or (e.extra and e.extra.startswith(q)):
                rank = 2
            elif q in e.folded_name:
                rank = 3
            else:
                continue
            scored.append(((rank, _KIND_ORDER[e.kind], *e.order, e.folded_name), e))
        scored.sort(key=lambda s: s[0])
        return [self._place(e.kind, e.code) for _, e in scored[:limit]]

    def tree(self, ref: PlaceRef, depth: int | None = None) -> TreeNode | None:
        """The Place and what it contains: Region -> (sub-Regions or) countries -> cities ->
        airports. `depth` limits how many levels below `ref` are expanded (None: all)."""
        if not self.known(ref):
            return None
        return self._node(ref.kind, ref.code, depth, via=None)

    # --- internals -----------------------------------------------------------------------------
    def _node(self, kind: str, code: str, depth: int | None, via: str | None) -> TreeNode:
        node = TreeNode(**self._place(kind, code).model_dump(), via=via)
        if kind == "airport" or depth == 0:
            return node
        below = None if depth is None else depth - 1
        children: list[TreeNode] = []
        if kind == "region":
            region = self.regions[code]
            if region.children:
                children = [self._node("region", c, below, None) for c in region.children]
            else:
                children = [
                    self._node(
                        "country",
                        c,
                        below,
                        self.countries[region.via[c]][0] if c in region.via else None,
                    )
                    for c in sorted(region.countries, key=lambda c: self.countries[c][0])
                ]
        elif kind == "country":
            in_country = sorted(self._by_country.get(code, ()))
            city_ids = sorted(
                {self.airports[a].city for a in in_country if self.airports[a].city},
                key=lambda c: self.cities[c][0],
            )
            children = [self._node("city", c, below, None) for c in city_ids]
            children += [
                self._node("airport", a, below, None)
                for a in in_country
                if not self.airports[a].city
            ]
        elif kind == "city":
            children = [self._node("airport", a, below, None) for a in sorted(self._by_city[code])]
        node.children = children
        return node

    def _place(self, kind: str, code: str) -> Place:
        match kind:
            case "airport":
                a = self.airports[code]
                where = [self.cities[a.city][0]] if a.city else []
                where.append(self.countries[a.country][0])
                return Place(
                    kind=kind, code=code, name=a.name, context=", ".join(where), airport_count=1
                )
            case "city":
                name, country = self.cities[code]
                return Place(
                    kind=kind,
                    code=code,
                    name=name,
                    context=self.countries[country][0],
                    airport_count=len(self._by_city.get(code, ())),
                )
            case "country":
                name, _ = self.countries[code]
                owner = self.sovereign.get(code)
                return Place(
                    kind=kind,
                    code=code,
                    name=name,
                    context=f"territory of {self.countries[owner][0]}" if owner else None,
                    airport_count=len(self._by_country.get(code, ())),
                )
            case "region":
                region = self.regions[code]
                return Place(
                    kind=kind,
                    code=code,
                    name=region.name,
                    context=f"{len(region.countries)} countries",
                    airport_count=len(self.airports_of(PlaceRef(kind="region", code=code))),
                )
        raise ValueError(kind)


@cache
def default_reference() -> ReferenceData:
    """The bundled snapshot, loaded once per process."""
    return ReferenceData.load(DATA_DIR)


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _regions(
    spec: dict, countries: dict[str, tuple[str, str]]
) -> tuple[dict[str, str], dict[str, _Region]]:
    def check(codes, where: str) -> list[str]:
        unknown = [c for c in codes if c not in countries]
        if unknown:
            raise ValueError(f"regions.toml {where}: unknown country codes {unknown}")
        return list(codes)

    sovereign = dict(spec.get("territories", {}))
    check([*sovereign, *sovereign.values()], "[territories]")
    sovereigns = [c for c in countries if c not in sovereign]

    regions: dict[str, _Region] = {}
    for r in spec["regions"]:
        rid = r["id"]
        if r.get("all_countries"):
            members = set(countries)
        else:
            members = (
                {c for c in sovereigns if countries[c][1] == r["continent"]}
                if "continent" in r
                else set()
            )
            members |= set(check(r.get("countries", []), rid))
            members |= set(check(r.get("add", []), rid))
            members -= set(check(r.get("remove", []), rid))
        via: dict[str, str] = {}
        if r.get("territories", True):
            for t, owner in sovereign.items():
                if owner in members and t not in members:
                    via[t] = owner
            members |= set(via)
        regions[rid] = _Region(
            rid, r["name"], frozenset(members), via, tuple(r.get("children", ()))
        )

    for region in regions.values():
        for child in region.children:
            if child not in regions:
                raise ValueError(f"regions.toml {region.code}: unknown child Region {child!r}")
        if region.children:
            covered = frozenset().union(*(regions[c].countries for c in region.children))
            if missing := region.countries - covered:
                raise ValueError(f"regions.toml {region.code}: children miss {sorted(missing)}")
    return sovereign, regions
