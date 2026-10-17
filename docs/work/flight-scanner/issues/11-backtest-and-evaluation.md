# 11: Backtest and evaluation page

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** The owner can see whether Alerts were actually good and tune Watches. Each past Deal is classified from later observations as a real dip or not; Alert rate, precision and feedback are summarised per Watch.

**Blocked by:** 05, 06

**Status:** ready-for-agent

- [ ] A model classifies each past Deal: did the price for those dates later return toward its Baseline (real dip) or stay low?
- [ ] Per-Watch metrics: precision, Alert rate per week, distribution of % below Baseline, 👍/👎 counts joined to classifications.
- [ ] Backtest page shows these per Watch.
- [ ] Seam-1 test with scripted history yields the expected classification; seam-2 tests for the backtest endpoint.
