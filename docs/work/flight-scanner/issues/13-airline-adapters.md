# 13: Ryanair and Wizz adapters (off by default)

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Optional live Leg prices for low-cost carriers. Calendar adapters for Ryanair and Wizz implement the source-adapter interface at low request rates without any bot-protection bypass, and stay disabled until the owner enables them (ADR-0002).

**Blocked by:** 09

**Status:** ready-for-agent

- [ ] Ryanair and Wizz adapters produce Leg prices per route per day from public calendar endpoints.
- [ ] Disabled by default behind an explicit configuration flag; the system runs fully without them.
- [ ] Low request rate with backoff; no proxy rotation, CAPTCHA solving or bot-protection bypass; an adapter that gets blocked disables itself and reports on the data-health page.
- [ ] A terms-of-service note accompanies the configuration flag.
- [ ] Seam-3 contract tests on recorded payloads for each adapter.
