# 04: Trip patterns and Round trip composition

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Watches support every Trip pattern the owner described, and round trips are composed from Leg prices. Each preset normalises to a departure window plus Stay nights and expands to concrete date pairs for "today"; outbound and return Leg prices are paired and compared with any single-ticket Round-trip price, keeping the cheaper (ADR-0001).

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Presets supported: fixed dates; N–M Stay nights departing within a month; N–M Stay nights within a rolling window from today; fixed departure with N–M Stay nights; target date ± K days with N–M Stay nights; optional latest return date; one-way.
- [ ] Only the departure must fall in the window; the return may fall after it (28 Nov → 2 Dec satisfies "in November").
- [ ] Rolling windows slide daily with the injected clock.
- [ ] The editor shows the resolved departure window and Stay-night range for any preset.
- [ ] Composition pairs outbound and return Leg prices satisfying the pattern, compares against the Round-trip price for the same dates, and keeps the cheaper, labelled single ticket or two separate tickets.
- [ ] No Self-transfer within one direction is ever composed.
- [ ] Watches whose departure window has fully passed are marked expired and stop generating demand.
- [ ] Seam-1 tests cover each preset, a return after the window, a cheaper single-ticket Round-trip price beating two Leg prices, and expiry.
