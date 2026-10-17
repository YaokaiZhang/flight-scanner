# 08: Verification and Price insights

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Candidates are checked live before the owner trusts them, and the same check teaches the system what is normal. The SerpApi Google Flights adapter verifies top Candidates in round-trip mode for the Watch's adults within the free monthly budget; its Price insight becomes a Baseline tier and its price history is stored as Fare observations.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] SerpApi adapter implements the source-adapter interface for Verification, enforcing a 250/month budget (~8/day) with quota accounting.
- [ ] Candidates are ranked by % below Baseline and Watch priority; the top ones within budget are verified in round-trip mode for the Watch's adult count.
- [ ] Outcomes: Verified Deal, failed (recorded, not alerted), or Unverified Deal when the budget is exhausted (clearly labelled).
- [ ] Price insight (typical price range and price history) is stored; it is a Baseline tier between the country Baseline and the provisional Baseline.
- [ ] A Candidate judged only against a provisional Baseline is re-judged against the Price insight during Verification.
- [ ] Price-insight history points are ingested as Fare observations and count toward route-Baseline support.
- [ ] Works if price history is absent from a response (typical range only).
- [ ] Seam-3 contract test on recorded SerpApi payloads.
- [ ] Seam-1 tests: pass, fail, budget exhaustion, provisional → Price insight re-judgement, history backfill making a route meet the 7-day rule.
