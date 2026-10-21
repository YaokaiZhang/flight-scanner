# 13: Ryanair and Wizz adapters (off by default)

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Optional live Leg prices for low-cost carriers. Calendar adapters for Ryanair and Wizz implement the source-adapter interface at low request rates without any bot-protection bypass, and stay disabled until the owner enables them (ADR-0002).

**Blocked by:** 09

**Status:** resolved

- [x] Ryanair and Wizz adapters produce Leg prices per route per day from public calendar endpoints.
- [x] Disabled by default behind an explicit configuration flag; the system runs fully without them.
- [x] Low request rate with backoff; no proxy rotation, CAPTCHA solving or bot-protection bypass; an adapter that gets blocked disables itself and reports on the data-health page.
- [x] A terms-of-service note accompanies the configuration flag.
- [x] Seam-3 contract tests on recorded payloads for each adapter.

## Comments

- Branch `ticket/13-airline-adapters`: `sources/ryanair.py` (farfnd cheapestPerDay calendar) and `sources/wizz.py` (timetable search) over a shared `sources/polite_http.py` (6 req/min, backoff, `SourceBlocked` on 403/challenge, never bypassed); on only with FS_SOURCES + FS_ENABLE_RYANAIR/WIZZ=true (ToS note in .env.example); blocks persist in `app.source_blocks` (GET /sources/blocked; `python -m flight_scanner unblock`), planner skips blocked sources and honours adapter `default_budget`/`rescan_after` (2 h). Data-health page itself is ticket 10. Payload fixtures are representative, not live captures. Notes: flight-scanner-notes/ticket-13.md.
