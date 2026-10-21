"""Rebuild the trimmed OurAirports snapshot in `places/data/` from the full public-domain CSVs.

    curl -sSfLO https://davidmegginson.github.io/ourairports-data/airports.csv   # and countries.csv
    python -m flight_scanner.places.refresh --ourairports DIR --fetched YYYY-MM-DD

Keeps airports with an IATA code and scheduled service (no heliports, seaplane bases or closed
fields), derives Cities from the municipality, and writes `airports.csv`, `cities.csv`,
`countries.csv` and `snapshot.toml`. City ids are derived from the country (or the ISO region, when
one city name occurs in several regions of a country) and the name, so they stay stable between
snapshots as long as OurAirports keeps the municipality. Watches store these ids.
Regions are hand-written in `data/regions.toml`; this script does not touch them.
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
KEEP_TYPES = {"large_airport", "medium_airport", "small_airport"}


def slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-") or "x"


def city_name(municipality: str) -> str:
    """'Helsinki (Vantaa)' -> 'Helsinki'; 'London, Essex' -> 'London'."""
    name = re.sub(r"\s*\(.*?\)\s*", " ", municipality).split(",")[0]
    return " ".join(name.split())


def _write(path: Path, header: list[str], rows) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def build(src: Path, out: Path, fetched: str) -> dict[str, int]:
    with open(src / "countries.csv", encoding="utf-8", newline="") as f:
        countries = [r for r in csv.DictReader(f) if r["code"] != "ZZ"]
    known = {c["code"] for c in countries}
    with open(src / "airports.csv", encoding="utf-8", newline="") as f:
        airports = [
            r
            for r in csv.DictReader(f)
            if r["iata_code"]
            and r["scheduled_service"] == "yes"
            and r["type"] in KEEP_TYPES
            and r["iso_country"] in known
        ]

    regions_of: dict[tuple[str, str], set[str]] = defaultdict(set)
    for a in airports:
        if name := city_name(a["municipality"]):
            regions_of[(a["iso_country"], name)].add(a["iso_region"])

    cities: dict[str, tuple[str, str]] = {}
    rows = []
    for a in sorted(airports, key=lambda r: r["iata_code"]):
        city_id = ""
        if name := city_name(a["municipality"]):
            ambiguous = len(regions_of[(a["iso_country"], name)]) > 1
            city_id = f"{a['iso_region'] if ambiguous else a['iso_country']}-{slug(name)}"
            cities.setdefault(city_id, (name, a["iso_country"]))
        lat, lon = float(a["latitude_deg"]), float(a["longitude_deg"])
        rows.append(
            [
                a["iata_code"],
                a["name"],
                a["type"],
                city_id,
                a["iso_country"],
                f"{lat:.4f}",
                f"{lon:.4f}",
            ]
        )

    out.mkdir(parents=True, exist_ok=True)
    _write(out / "airports.csv", ["iata", "name", "type", "city", "country", "lat", "lon"], rows)
    _write(
        out / "cities.csv", ["id", "name", "country"], ([k, *v] for k, v in sorted(cities.items()))
    )
    _write(
        out / "countries.csv",
        ["code", "name", "continent"],
        (
            [c["code"], c["name"], c["continent"]]
            for c in sorted(countries, key=lambda c: c["code"])
        ),
    )
    counts = {"airports": len(rows), "cities": len(cities), "countries": len(countries)}
    (out / "snapshot.toml").write_text(
        "# Written by `python -m flight_scanner.places.refresh`; do not edit by hand.\n"
        'source = "OurAirports (public domain), https://ourairports.com/data/"\n'
        f'version = "ourairports-{fetched}"\n'
        'filter = "iata_code set, scheduled_service = yes, type in large/medium/small_airport"\n'
        + "".join(f"{k} = {v}\n" for k, v in counts.items())
    )
    return counts


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--ourairports", type=Path, required=True, help="dir with airports/countries.csv"
    )
    p.add_argument("--fetched", required=True, help="date the CSVs were downloaded (YYYY-MM-DD)")
    p.add_argument("--out", type=Path, default=DATA_DIR)
    a = p.parse_args()
    print(build(a.ourairports, a.out, a.fetched))


if __name__ == "__main__":
    main()
