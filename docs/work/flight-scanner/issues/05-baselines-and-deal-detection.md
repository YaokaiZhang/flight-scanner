# 05: Baselines and Deal detection

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** The system learns what "normal" is and alerts on fares well below it. Baselines are computed per (origin city, destination airport, departure month, Stay-night bucket), fall back to the destination country, and to a provisional low-confidence estimate; composed trips at least the Watch's sensitivity below the Baseline (and under the Price threshold if set) become Candidates. Until Verification exists, Candidates become Unverified Deals.

**Blocked by:** 02, 04

**Status:** resolved

- [x] Stay-night buckets: one-way, 1–2, 3–4, 5–7, 8–14, 15+.
- [x] Route Baseline: median of daily-minimum prices over a trailing 60-day window, MAD as spread; requires ≥20 observations over ≥7 distinct observation days.
- [x] Falls back to the destination-country Baseline under the same support rule, then to a provisional cross-sectional Baseline flagged low-confidence.
- [x] Baselines are versioned (computed_at, method, support); each Deal records the Baseline version and tier it was judged against.
- [x] A trip becomes a Candidate when ≥ sensitivity below Baseline and under the Price threshold if set; with no Baseline at all, only a Price threshold can produce one.
- [x] Route explorer shows the Baseline band alongside price history.
- [x] Seam-1 tests: three weeks of normal prices then a fare 50% below yields a Deal; 20 observations all on 2 days does not satisfy support; country fallback; provisional tier; threshold and Baseline both applied.

## Comments

- Branch `ticket/05-baselines-and-deal-detection`: route/country/provisional Baselines (dbt `baselines`, versioned in `baseline_versions`), Deal test in `candidates`, Deals record the Baseline version, Baseline band in the route explorer, Baseline estimator first in the scan planner. Price-insight tier left to ticket 08. Notes: flight-scanner-notes/ticket-05.md.
