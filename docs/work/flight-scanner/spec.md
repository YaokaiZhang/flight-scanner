# Spec: Flight Scanner v1

Status: ready-for-agent

_Vocabulary follows `CONTEXT.md`. Decisions respect ADR-0001 (Round trips from Leg prices plus Round-trip prices), ADR-0002 (free sources, cached-first, budgeted Verification) and ADR-0003 (operational loop on verda, analytical layer on Databricks Free Edition). The background PRD is `docs/PRD.md`._

## Problem Statement

I want to travel cheaply, but cheap fares appear briefly and unpredictably. Checking flight sites by hand across many destinations and flexible dates is tedious, and I miss most of the good fares. Ordinary price alerts only tell me when a fare is under a fixed number. That fires constantly on routes that are always cheap and never on routes that are normally expensive. What I actually want to know is when a trip I care about is **significantly cheaper than it normally costs**. For example, Helsinki to Egypt in November is normally about €200 return, so €100 is worth knowing about. My wishes are also wide and fuzzy: "somewhere in Europe but not Sweden, or Egypt", "3–6 nights some time in November", "around 22 November".

## Solution

A personal, self-hosted scanner that I configure through a web UI:

- I create **Watches** that describe what I want. Each Watch has:
  - origin and destination Places (airports, cities, countries or Regions), with Exclusions
  - a Trip pattern (fixed or flexible dates, one-way or round trip, Stay nights)
  - a passenger count and an optional Price threshold
- The system continuously collects prices from free sources. It learns a **Baseline** (the normal per-adult price) for comparable trips and finds **Candidates** that are well below it.
- It checks the best Candidates live (**Verification**) within a free budget.
- It sends me an **Alert** by email and/or Telegram for each **Deal**, without repeating itself.
- I can browse price history, see whether the data is healthy, rate Alerts, and see how accurate past Alerts were.

## User Stories

### Watches and Places

1. As the owner, I want to create a Watch with one or more origin Places, so that I can depart from any of several nearby airports (e.g. HEL or TLL).
2. As the owner, I want to create a Watch with one or more destination Places, so that one Watch covers everywhere I would be happy to go.
3. As the owner, I want to choose an airport, a city, a country or a Region as a Place, so that I can be as specific or as vague as I like.
4. As the owner, I want to choose "Anywhere" as a destination, so that I can discover trips when I have no destination in mind.
5. As the owner, I want to combine Places, e.g. Europe plus Egypt, so that my destination can span Regions and countries.
6. As the owner, I want to add Exclusions to a Watch, e.g. Europe excluding Sweden, so that places I don't want never produce Alerts.
7. As the owner, I want to add Exclusions to the origin side too, so that a wide origin Region can skip airports I can't reach.
8. As the owner, I want to search Places by name or code with autocomplete, so that I can add them quickly.
9. As the owner, I want to browse Regions as a tree (Region → country → city → airport), so that I understand what a Region contains.
10. As the owner, I want to see how many airports a Watch's origins and destinations resolve to, so that I know how wide the Watch is.
11. As the owner, I want territories to belong to their sovereign country's Region (e.g. the Canary Islands in Europe), so that Region membership is predictable.
12. As the owner, I want a Watch's resolved airports to update when reference data changes, so that new airports are covered without editing the Watch.
13. As the owner, I want to edit a Watch, so that I can refine it over time.
14. As the owner, I want to pause and resume a Watch, so that I can stop Alerts temporarily without losing the configuration.
15. As the owner, I want to delete a Watch, so that I can remove searches I no longer care about.
16. As the owner, I want to name a Watch, so that I can recognise it in Alerts and the UI.

### Trip patterns

17. As the owner, I want to choose one-way or round trip per Watch, so that I can watch both kinds of travel.
18. As the owner, I want fixed dates (e.g. 11 Nov → 15 Nov), so that I can watch a trip whose dates are already decided.
19. As the owner, I want "3–6 Stay nights departing any day in November", so that I can watch a flexible trip inside a month.
20. As the owner, I want the return to be allowed after the end of the departure window (e.g. 28 Nov → 2 Dec), so that late-month departures still count.
21. As the owner, I want "2–4 Stay nights within the next two months", rolling forward daily, so that a Watch stays useful without editing.
22. As the owner, I want "depart 22 Nov for 3–5 nights", so that I can fix the departure but keep the length flexible.
23. As the owner, I want "3–5 nights departing 22 Nov ± 2 days", so that I can be flexible around a target date.
24. As the owner, I want an optional latest return date, so that a trip never ends after a fixed commitment.
25. As the owner, I want the UI to show the resolved departure window and Stay-night range for any preset, so that I can check the system understood me.
26. As the owner, I want trip length counted in Stay nights, so that "3 nights" is unambiguous.
27. As the owner, I want Watches whose departure window has fully passed to be marked expired and stop scanning, so that they don't use budget.

### Watch settings

28. As the owner, I want to set the number of adults on a Watch, so that Deals reflect what my group would actually pay.
29. As the owner, I want an optional Price threshold, as a total or per adult, so that I only hear about trips within my budget.
30. As the owner, I want to set how far below the Baseline a fare must be (default 30%), so that I can make a Watch more or less sensitive.
31. As the owner, I want to choose immediate Alerts or a daily Digest per Watch, so that low-priority Watches don't interrupt me.
32. As the owner, I want to choose email, Telegram or both per Watch, so that Alerts reach me where I want them.

### Data collection

33. As the owner, I want prices collected automatically on a schedule, so that I never have to search by hand.
34. As the owner, I want overlapping Watches to share scans, so that two Watches covering HEL → Europe don't double the work.
35. As the owner, I want scans prioritised (near departure dates, volatile routes, routes close to a Deal first), so that the limited budget is spent where Deals are most likely.
36. As the owner, I want each source's rate limit and quota respected automatically, so that I'm never blocked or billed.
37. As the owner, I want the system to keep working when one source fails, so that a single outage doesn't stop Alerts.
38. As the owner, I want every raw source response kept, so that any processing mistake can be fixed by reprocessing history.
39. As the owner, I want the Ryanair and Wizz adapters disabled until I explicitly enable them, so that I make a conscious choice about their terms of service.
40. As the owner, I want both Leg prices and Round-trip prices used, so that a single return ticket that undercuts two one-ways is not missed.
41. As the owner, I want trips with any number of stops considered, so that I don't miss cheap fares, while seeing stops and travel time in each Alert.
42. As the owner, I don't want Self-transfer within one direction considered, so that I'm never alerted to fragile connections.

### Baselines, Candidates and Deals

43. As the owner, I want the Baseline learned from the system's own price history, so that "cheap" means cheap for that specific trip.
44. As the owner, I want comparable trips grouped by origin city, destination airport, departure month and Stay-night bucket, so that a 3-night November trip isn't compared with a 2-week July one.
45. As the owner, I want a sparse route to fall back to a destination-country Baseline, so that new or rare routes can still produce Deals.
46. As the owner, I want a Baseline to require observations spread over at least 7 distinct days, so that one burst of scans can't define "normal".
47. As the owner, I want historical prices from a Price insight used when the system's own history is too thin, so that new routes can produce Deals from day one instead of staying silent.
48. As the owner, I want a Price insight's price history stored as Fare observations, so that it also counts toward the route's own Baseline.
49. As the owner, I want a provisional low-confidence Baseline to rank trips for Verification when no other Baseline exists, so that the Verification budget is spent on the most promising new routes.
50. As the owner, I want a Watch with a Price threshold to alert on fares under the threshold even when no Baseline exists, so that I'm never left blind on a new route.
51. As the owner, I want both the Baseline test and the Price threshold applied when both exist, so that a Deal is cheap both relatively and absolutely.
52. As the owner, I want Baselines to be versioned, and each Deal to record which Baseline tier it was judged against, so that I can see why a past Alert fired.
53. As the owner, I want suspicious data (empty scans, sudden source-wide price jumps, stale data) to block Deal detection for the affected slice, so that bad data doesn't cause false Alerts.

### Verification

54. As the owner, I want the best Candidates checked live for my passenger count before alerting, so that I'm not sent fares that no longer exist.
55. As the owner, I want Verification done as a round trip, so that a cheaper single-ticket return is found if one exists.
56. As the owner, I want Verification to stay within the free monthly budget, so that the system costs nothing.
57. As the owner, I want Candidates to be alerted as Unverified when the budget is spent, clearly labelled, so that I still hear about them and know how much to trust them.
58. As the owner, I want Candidates that fail Verification recorded, so that source accuracy can be measured.

### Alerts and Digests

59. As the owner, I want each Alert to show route, dates, airlines, stops, total travel time, total and per-adult price, Baseline and % below, Verified/Unverified, and "2 separate tickets" where relevant, so that I can decide quickly.
60. As the owner, I want a booking link in each Alert, so that I can act immediately.
61. As the owner, I want an Alert sent once per Watch, route and dates, so that a long-lived fare doesn't spam me.
62. As the owner, I want a new Alert if the price drops a further ≥10%, so that I hear about even better prices.
63. As the owner, I want a new Alert if a fare reappears after being gone at least 24 h, so that returning Deals are not silently suppressed.
64. As the owner, I want a daily Digest that lists all Deals for Watches in Digest mode, so that low-priority Watches send one message a day.
65. As the owner, I want optional Deal context ("why is this cheap?") added to an Alert without delaying it by more than 60 s, so that I can judge whether the Deal is real.
66. As the owner, I want 👍/👎 buttons on Telegram Alerts, so that I can rate Alerts in one tap.

### UI

67. As the owner, I want a Deals feed with filtering by Watch and status, so that I can review recent Deals in one place.
68. As the owner, I want to rate a Deal 👍/👎 in the UI, so that I can give feedback outside Telegram.
69. As the owner, I want a route explorer that charts price history per route and date with the Baseline band, so that I can see what "normal" looks like.
70. As the owner, I want a data-health page showing each source's freshness, last success, coverage gaps, scan backlog and Verification budget used, so that I can trust the system or see what is wrong.
71. As the owner, I want a backtest page showing, per Watch, how many past Deals were real dips, the Alert rate per week, and my feedback, so that I can tune sensitivity.
72. As the owner, I want the UI reachable only through an SSH tunnel to verda, so that it is never exposed publicly.

### Evaluation

73. As the owner, I want each past Deal checked against later prices (did the price return to the Baseline?), so that detection quality is measured objectively.
74. As the owner, I want my 👍/👎 ratings joined to backtest results, so that objective and subjective quality can be compared.

### Analytical layer

75. As the owner, I want history exported daily to Databricks Free Edition, where Baselines and backtests are recomputed at scale, so that the project demonstrates a lakehouse workflow.
76. As the owner, I want Alerts to keep working on the last published Baselines when Databricks is unavailable, so that its quotas never affect me.

### Operation and portfolio

77. As the owner, I want the whole operational stack to start with one command on a fresh host, so that it is reproducible.
78. As the owner, I want all secrets supplied by environment, never committed, so that the public repository is safe.
79. As a portfolio reviewer, I want a README explaining cached discovery plus live Verification and how it mirrors metasearch platforms, so that I understand the design trade-offs.
80. As a portfolio reviewer, I want the demo to run on Travelpayouts and the SerpApi free tier alone, so that I can reproduce it without grey-area sources.

## Implementation Decisions

### Modules

Each module is a deep module behind a small interface.

- **Reference data and Places.** Loads airports, cities and countries (OurAirports plus Travelpayouts codes) and Region definitions from a versioned file in the repo. Interface: search Places; resolve `include − exclude` into an airport set; list a Region's tree.
- **Trip patterns.** Normalises every preset into `{kind, departure_window (absolute or rolling offsets), stay_nights [min,max], return_by?}` and expands it, for a given "today", into concrete (departure date, return date) pairs. Interface: `normalise(preset)` and `expand(pattern, today)`.
- **Watches.** Persists Watches and their Place references, settings and delivery choices; derives the active, de-duplicated set of (origin airport, destination airport or wildcard, month) demands.
- **Source adapters.** One adapter per source behind a single interface: `plan(demands, budget) → requests`, `fetch(request) → raw payload`, `parse(raw payload) → Leg prices and/or Round-trip prices`. Adapters own their rate limiting, backoff and quota accounting. Sources:
  - Travelpayouts: cached Leg and Round-trip prices
  - Ryanair and Wizz calendar endpoints: off by default
  - SerpApi Google Flights: Verification only, round-trip mode, free-tier budget
- **Scan planner.** Turns demands into scan tasks per source, ranked by: proximity of departure, recent volatility, distance from Deal, time since last scan. Never exceeds a source's budget; records skipped tasks.
- **Ingestion and storage layers.**
  - Raw: immutable compressed payloads partitioned by source and date.
  - Staging: dbt models producing normalised Leg prices and Round-trip prices in EUR per adult.
  - History: change-only Leg-price and Round-trip-price history, with validity intervals.
- **Trip composition.** For each Watch, pairs outbound and return Leg prices that satisfy the Trip pattern, compares the pair with any Round-trip price for the same dates, and keeps the cheaper, labelled single ticket or two separate tickets. Uses Leg prices directly for one-way Watches. No Self-transfer.
- **Baselines.**
  - Key: (origin city, destination airport, departure month, Stay-night bucket), with buckets one-way, 1–2, 3–4, 5–7, 8–14 and 15+.
  - Statistic: median of daily-minimum prices over a trailing window (default 60 days), with MAD as the spread measure.
  - Minimum support: at least 20 observations spread over at least 7 distinct observation days.
  - Tiers, tried in order; the Deal records which one applied:
    1. Route Baseline from own history (incl. stored Price-insight history) meeting minimum support.
    2. Destination-country Baseline from own history meeting minimum support.
    3. Price insight: Google's typical price range (and recent price history) returned by the Verification call for that trip.
    4. Provisional cross-sectional Baseline (distribution across all departure dates in the month), flagged low-confidence. Used only to rank trips for Verification, and for Unverified Deals when the budget is exhausted.
  - A Price insight's price-history points are ingested as Fare observations, so one Verification call also backfills history for that Baseline key.
  - Every Baseline row is versioned (computed_at, method, support).
- **Deal detection.** Produces Candidates when the price is at least the Watch's sensitivity below the Baseline, and under the Price threshold if one is set. When only a provisional Baseline exists, a trip becomes a Candidate if it passes the test against it; Verification then re-judges it against the Price insight. With no Baseline at all, only a Price threshold can produce a Candidate. Data-quality checks gate detection per slice.
- **Verification.** One SerpApi call returns both the live price and a Price insight. Ranks Candidates by % below Baseline and Watch priority. Spends the SerpApi budget on the top ones in round-trip mode for the Watch's adult count. Each Candidate ends as a Verified Deal, failed, or an Unverified Deal (when the budget is exhausted).
- **Alerts.**
  - Dedup key: (Watch, origin airport, destination airport, outbound date, return date).
  - Re-alert on a further ≥10% drop, or on reappearance after ≥24 h absence.
  - Digest batching per Watch.
  - A single notifier interface with email (SMTP) and Telegram implementations; Telegram carries 👍/👎 callbacks.
  - Optional Deal-context enrichment with a 60 s cap.
- **Evaluation.** A backtest model classifying each past Deal as a real dip or not from later observations, plus Alert-rate and feedback aggregates per Watch.
- **HTTP API (FastAPI).** Reads from the marts layer only. Resources: Places (search, resolve, tree), Watches (CRUD, pause, preview of resolved airports and window), Deals (feed, detail, feedback), route history, data health, backtest.
- **Web UI (Next.js).** Pages: Watches (list and editor), Deals, Route explorer, Data health, Backtest. Talks only to the HTTP API.
- **Analytical export (Databricks).** A daily export of history and staging as Parquet to a Unity Catalog volume. Bronze/silver/gold tables. Baseline recompute and backtest jobs. Results written back to Postgres as new Baseline versions.

### Architecture

- Orchestration: Dagster software-defined assets, with per-source schedules, sensors chaining ingestion → history → composition → detection → Verification → Alerts, partitions by source and date, and asset checks as data-quality gates.
- Transformations: dbt with adapter-portable SQL in shared models, so they run on Postgres and Databricks (ADR-0003).
- Storage: Postgres for staging, history and marts; local volume for raw.
- Deployment: Docker Compose on verda (Postgres, Dagster webserver and daemon, API, web). The UI and API bind to localhost and are reached via SSH tunnel.
- Configuration: all keys and tokens from environment variables. Airline adapters behind an explicit enable flag.
- Clock: an injectable clock used by Trip-pattern expansion, Baseline windows, dedup cooldowns and Digest scheduling.

### Defaults

| Setting | Default |
|---|---|
| Sensitivity | 30% below Baseline |
| Re-alert drop | 10% |
| Reappearance gap | 24 h |
| Baseline window | 60 days |
| Minimum support | 20 observations over ≥7 distinct days |
| Travelpayouts cadence | 30–60 min |
| Airline adapter cadence | 1–2 h |
| Verification budget | 250/month (~8/day) |

## Testing Decisions

- **What a good test is:** it drives the system only through a seam and asserts only on what comes out of the seam. It never asserts on internal tables, intermediate models or function calls. Internals can be refactored freely while tests stay green.
- **Seam 1: Pipeline, sources in → Alerts out (primary).**
  - Input: fake source adapters returning recorded raw payloads, scripted per scan time.
  - Output: a recording notifier.
  - In between: real Postgres, real dbt models, Dagster assets executed in-process, and the injectable clock.
  - Scenarios cover: Place resolution with Exclusions; every Trip-pattern preset including rolling windows and returns after the window; pairing two separate tickets against a cheaper single-ticket Round-trip price; each Baseline tier (route, country, Price insight, provisional) including the 7-day spread rule and Price-insight history backfilling the route Baseline; Price-threshold-only Candidates; Verification pass, fail and budget exhaustion (Unverified); dedup, re-alert on a further drop, re-alert on reappearance; Digest batching; a data-quality gate blocking detection; a source outage not stopping other sources.
- **Seam 2: HTTP API.** Exercised with an HTTP client against real Postgres. Covers Watch CRUD and validation, Place search, resolution and tree, Deals feed and feedback, route history, data health and backtest responses.
- **Seam 3: Source-adapter contracts.** One test per adapter parses recorded raw payloads into Leg prices and Round-trip prices and checks the normalised shape and values. Recorded payloads are refreshed when a source changes.
- **Not separately tested:**
  - The Next.js UI: one Playwright smoke test of create Watch → see Deal.
  - The Databricks layer: the shared dbt models are already tested on Postgres through seam 1.
  - Dagster wiring: covered by seam 1.
- **dbt tests** (not-null, unique, accepted values, relationships) on every model, as data contracts rather than behaviour tests.
- **Prior art:** none. This is a new codebase, and these tests set the pattern.

## Out of Scope

- Multiple users, sign-up, authentication, public exposure of the UI.
- Booking or payment.
- Baggage-inclusive price normalisation; max-stops and layover limits.
- Self-transfer within one direction.
- Children and infant passengers.
- SMS notifications.
- Paid data sources or paid tiers; large-scale scraping; any bypass of bot protection.
- An AI agent as a price source (used only for Deal context).
- Snowflake deployment (documented as an option only).

## Further Notes

- Known limitations to surface in the UI and README:
  - Cached data covers only routes recently searched on Aviasales.
  - A single-ticket return fare on dates no source covered is missed.
  - Cached prices are for one adult, so multi-passenger prices are only exact after Verification.
  - Prices exclude baggage.
- Suggested build order follows the PRD milestones M0–M7: skeleton and Places → ingestion → Watches and detection → Alerts → Verification and planning → evaluation → lakehouse → extras.
- The verda project folder is not yet a git repository; initialise one before implementation starts.
