# 02: Travelpayouts ingestion and price history

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Real prices start flowing. The Travelpayouts adapter fetches cached Leg prices and Round-trip prices for the routes and months active Watches need, stores raw payloads, normalises them (EUR, per adult) and collapses repeated identical observations into change-only price history. The owner can open a route explorer page and see a route's price history over time.

**Blocked by:** 01

**Status:** resolved

- [x] Travelpayouts adapter implements the source-adapter interface, enforcing its rate limit and backoff.
- [x] Staging produces normalised Leg prices and Round-trip prices in EUR per adult from raw payloads.
- [x] History stores one row per price change with a validity interval; repeated identical observations do not add rows.
- [x] Any staging or history model can be rebuilt from raw payloads alone.
- [x] Seam-3 contract test parses recorded Travelpayouts payloads into the expected Leg prices and Round-trip prices.
- [x] Seam-1 test: three scans with an unchanged then changed price yield two history rows.
- [x] The route explorer page charts price history for a chosen route and departure date via the API.
- [x] dbt tests (not-null, unique, relationships) on every new model.

## Comments

- Branch `ticket/02-travelpayouts-ingestion`: Travelpayouts `prices_for_dates` adapter (rate limit, backoff, seam-3 contract tests on recorded payloads), FX + per-adult staging, change-only `history.*` dbt models, `rebuild` (re-parse raw store + dbt), `/routes` API and the Route explorer page. Real API not exercised (no token); set `TRAVELPAYOUTS_TOKEN` and add `travelpayouts` to `FS_SOURCES`.
