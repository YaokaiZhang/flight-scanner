# 02: Travelpayouts ingestion and price history

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Real prices start flowing. The Travelpayouts adapter fetches cached Leg prices and Round-trip prices for the routes and months active Watches need, stores raw payloads, normalises them (EUR, per adult) and collapses repeated identical observations into change-only price history. The owner can open a route explorer page and see a route's price history over time.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Travelpayouts adapter implements the source-adapter interface, enforcing its rate limit and backoff.
- [ ] Staging produces normalised Leg prices and Round-trip prices in EUR per adult from raw payloads.
- [ ] History stores one row per price change with a validity interval; repeated identical observations do not add rows.
- [ ] Any staging or history model can be rebuilt from raw payloads alone.
- [ ] Seam-3 contract test parses recorded Travelpayouts payloads into the expected Leg prices and Round-trip prices.
- [ ] Seam-1 test: three scans with an unchanged then changed price yield two history rows.
- [ ] The route explorer page charts price history for a chosen route and departure date via the API.
- [ ] dbt tests (not-null, unique, relationships) on every new model.
