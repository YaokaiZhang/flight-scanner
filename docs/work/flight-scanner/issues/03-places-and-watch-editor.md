# 03: Places, Regions, Exclusions and the Watch editor

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** The owner can describe where they want to go the way they think about it. Reference data (airports, cities, countries, Regions from a versioned definition file) is loaded; the owner searches Places, browses the Region tree, builds include/exclude sets for origins and destinations, and sees how many airports the Watch resolves to. The Watch editor gains all Watch settings.

**Blocked by:** 01

**Status:** resolved

- [x] Reference data loads airports, cities and countries; Regions come from a versioned file in the repo; territories belong to their sovereign country's Region (Canary Islands ⊂ Europe).
- [x] "Anywhere" is a Region containing all countries.
- [x] API: search Places by name or code, resolve include − exclude to an airport set, return a Region's tree.
- [x] Exclusions work on both origin and destination sides.
- [x] Resolved airport sets are recomputed when reference data changes.
- [x] Watch editor: Place picker with search, include/exclude chips, Region tree and resolved airport count; name, adults, optional Price threshold (total or per adult), sensitivity (default 30%), pause/resume, delete.
- [x] Seam-2 tests: Place search, resolution with Exclusions, Region tree, Watch validation.
- [x] Seam-1 test: a Watch for Europe excluding Sweden produces no Alert for a cheap fare to ARN but does for one to BCN.

## Comments

- Resolved on branch `ticket/03-places-and-watch-editor`: `flight_scanner.places` package (bundled OurAirports snapshot + versioned `regions.toml`), Places API (search/resolve/tree/regions), Watch edit/pause/resume/delete + sensitivity, Place picker in the Watch editor. Notes: flight-scanner-notes/ticket-03.md.
