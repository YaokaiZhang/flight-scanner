# 07: Alert dedup, re-alerts and Digest

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** The owner is told once, not every scan. Alerts are deduplicated per (Watch, origin airport, destination airport, outbound date, return date); a new Alert goes out only on a further price drop or a reappearance; Watches in Digest mode get one daily summary instead.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A Deal still present on later scans produces no further Alert.
- [ ] A further drop of ≥10% from the last alerted price produces a new Alert.
- [ ] A fare absent for ≥24 h that reappears as a Deal produces a new Alert.
- [ ] Per-Watch delivery choice: immediate or daily Digest; a Digest lists all Deals for that Watch since the last Digest.
- [ ] Seam-1 tests for each rule, driven by the injectable clock.
