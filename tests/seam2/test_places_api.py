"""Seam 2: Places over HTTP (search, resolution with Exclusions, Region tree).

Runs against the bundled reference snapshot (OurAirports + `regions.toml`), so expected values are
real-world facts: BCN is in Spain, ARN is in Sweden, the Canary Islands are Spanish.
"""

import pytest
from fastapi.testclient import TestClient

from flight_scanner.api import create_app


@pytest.fixture
def api(db):
    with TestClient(create_app(db)) as client:
        yield client


def search(api, q: str, **params) -> list[dict]:
    r = api.get("/places/search", params={"q": q, **params})
    assert r.status_code == 200
    return r.json()


def resolve(api, include: list[dict], exclude: list[dict] | None = None) -> dict:
    r = api.post("/places/resolve", json={"include": include, "exclude": exclude or []})
    assert r.status_code == 200, r.text
    return r.json()


EUROPE = {"kind": "region", "code": "europe"}
SWEDEN = {"kind": "country", "code": "SE"}


def ref(p: dict) -> tuple[str, str]:
    return p["kind"], p["code"]


# --- search ------------------------------------------------------------------------------------


def test_search_by_iata_code_puts_that_airport_first(api):
    [first, *_] = search(api, "bcn")
    assert ref(first) == ("airport", "BCN")
    assert "Barcelona" in first["name"]
    assert first["airport_count"] == 1


def test_search_by_name_finds_country_region_and_city(api):
    assert ref(search(api, "sweden")[0]) == ("country", "SE")
    assert ref(search(api, "Europe")[0]) == ("region", "europe")
    london = next(p for p in search(api, "london") if p["kind"] == "city")
    assert london["code"] == "GB-london"
    assert london["airport_count"] >= 4  # LHR, LGW, STN, LCY


def test_search_ignores_case_and_accents(api):
    assert ("airport", "AGP") in [ref(p) for p in search(api, "malaga")]


def test_search_results_carry_context_and_respect_the_limit(api):
    results = search(api, "san", limit=5)
    assert len(results) == 5
    bcn = search(api, "BCN")[0]
    assert "Spain" in bcn["context"]


def test_blank_search_returns_nothing(api):
    assert search(api, "  ") == []


# --- resolution --------------------------------------------------------------------------------


def test_region_minus_country_exclusion(api):
    europe = resolve(api, [EUROPE])
    sweden = resolve(api, [SWEDEN])
    result = resolve(api, [EUROPE], [SWEDEN])

    assert "ARN" in europe["airports"] and "ARN" in sweden["airports"]
    assert "ARN" not in result["airports"]
    assert "BCN" in result["airports"]
    assert result["airport_count"] == europe["airport_count"] - sweden["airport_count"]
    assert result["airport_count"] == len(result["airports"])


def test_combining_places_and_excluding_airports_and_cities(api):
    result = resolve(
        api,
        [EUROPE, {"kind": "country", "code": "EG"}],
        [{"kind": "airport", "code": "BCN"}, {"kind": "city", "code": "GB-london"}],
    )
    airports = set(result["airports"])
    assert {"HRG", "SSH", "AGP"} <= airports  # Egypt added to Europe
    assert not {"BCN", "LHR", "LGW"} & airports


def test_territories_belong_to_their_sovereign_countrys_region(api):
    europe = set(resolve(api, [EUROPE])["airports"])
    assert {"LPA", "TFS", "ACE"} <= europe  # Canary Islands are Spain, so Europe
    assert "RUN" in europe  # Réunion is French, so Europe too
    assert "HRG" not in europe


def test_anywhere_contains_every_airport(api):
    anywhere = resolve(api, [{"kind": "region", "code": "anywhere"}])
    assert {"HEL", "JFK", "SYD", "HRG", "LPA"} <= set(anywhere["airports"])
    total = sum(
        c["airport_count"]
        for c in api.get("/places/region/anywhere/tree?depth=1").json()["children"]
    )
    assert anywhere["airport_count"] == total


def test_resolving_an_unknown_place_is_rejected(api):
    r = api.post("/places/resolve", json={"include": [{"kind": "country", "code": "QQ"}]})
    assert r.status_code == 422
    assert "QQ" in r.text


# --- Region tree -------------------------------------------------------------------------------


def test_region_tree_goes_region_country_city_airport(api):
    tree = api.get("/places/region/europe/tree").json()
    assert ref(tree) == ("region", "europe")
    spain = next(c for c in tree["children"] if c["code"] == "ES")
    assert spain["kind"] == "country"
    barcelona = next(c for c in spain["children"] if c["code"] == "ES-barcelona")
    assert barcelona["kind"] == "city"
    assert [ref(a) for a in barcelona["children"]] == [("airport", "BCN")]
    assert tree["airport_count"] == resolve(api, [EUROPE])["airport_count"]


def test_region_tree_marks_territories_with_their_sovereign(api):
    tree = api.get("/places/region/europe/tree", params={"depth": 1}).json()
    reunion = next(c for c in tree["children"] if c["code"] == "RE")
    assert reunion["via"] == "France"
    assert reunion["children"] is None  # not expanded at depth 1


def test_anywhere_tree_lists_continents(api):
    tree = api.get("/places/region/anywhere/tree", params={"depth": 1}).json()
    names = {c["name"] for c in tree["children"]}
    assert {"Europe", "Africa", "Asia", "North America"} <= names
    assert all(c["kind"] == "region" for c in tree["children"])


def test_regions_are_listed_for_browsing(api):
    regions = api.get("/places/regions").json()
    codes = [r["code"] for r in regions]
    assert codes[0] == "anywhere"
    assert {"europe", "nordics", "schengen"} <= set(codes)


def test_tree_of_unknown_place_is_404(api):
    assert api.get("/places/region/atlantis/tree").status_code == 404
