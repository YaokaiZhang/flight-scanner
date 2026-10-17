# Flight Scanner — Product Requirements

_Status: agreed design, 2026-10-17. Vocabulary follows [CONTEXT.md](../CONTEXT.md); key decisions are in [docs/adr](./adr)._

## 1. Problem

Cheap fares appear briefly and unpredictably. Generic price alerts only answer "is it below €X?", which either fires constantly on cheap routes or never on expensive ones. The owner wants to be told when a trip they care about is **significantly cheaper than it normally is** — e.g. HEL→Egypt in November usually ~€200 return; a €100 fare is worth an Alert.

## 2. Goals and non-goals

**Goals**

- Detect Deals relative to a learned Baseline, across wide and flexible searches (many origins, regions with Exclusions, flexible Trip patterns).
- Alert quickly (within one scan cycle of the data appearing) via email and Telegram, without spam.
- Run at **€0/month** on free data sources and the owner's own host.
- Serve as a portfolio piece demonstrating data-engineering practice: layered ingestion, change-only history, data-quality gates, orchestration, backtesting, and a lakehouse analytical layer.

**Non-goals (v1)**

- Multiple users, sign-up or authentication.
- Booking or payment.
- Baggage-inclusive price normalisation, max-stops or layover limits.
- Self-transfer within one direction.
- SMS notifications.
- Large-scale scraping or any bypass of bot protection (ADR-0002).

## 3. User

A single owner, based in Helsinki, who configures Watches through a web UI and receives Alerts on phone and email.

## 4. User stories

1. As the owner, I create a Watch "HEL or TLL → Europe excluding Sweden, plus Egypt; 3–6 nights departing any day in November; 2 adults" and later edit, pause or delete it.
2. As the owner, I express flexible dates the way I think about them: fixed dates; "3–6 nights in November"; "2–4 nights within the next two months" (rolling); "departing Nov 22 for 3–5 nights"; "3–5 nights departing Nov 22 ± 2 days".
3. As the owner, I optionally set a Price threshold ("below €100") on a Watch.
4. As the owner, I receive an Alert with route, dates, airlines, stops, travel time, total and per-adult price, Baseline and % below, Verified/Unverified status, "2 separate tickets" when applicable, Deal context, and a booking link.
5. As the owner, I am not alerted twice for the same Deal unless its price falls further or it reappears after disappearing.
6. As the owner, I rate Alerts 👍/👎 from the UI or Telegram so detection can be tuned.
7. As the owner, I browse a route's price history against its Baseline band.
8. As the owner, I see whether the system is healthy: source freshness, coverage, verification budget, recent failures.

## 5. Functional requirements

### 5.1 Places, Regions and Exclusions

- Places are airports, cities, countries and Regions, from reference data (OurAirports airports/countries + Travelpayouts city codes).
- Regions: continents from the reference dataset plus named groups (Nordics, Schengen, EU, Middle East…) defined in a versioned YAML file. Territories belong to their sovereign country's region (Canary Islands ⊂ Spain ⊂ Europe).
- A Watch's origin and destination are each `include: [Place] − exclude: [Place]`, resolved to an airport set on save and re-resolved when reference data changes.
- "Anywhere" is a Region containing all countries.

### 5.2 Trip patterns

Every Trip pattern normalises to:

| Field | Meaning |
|---|---|
| `kind` | `one_way` or `round_trip` |
| `departure_window` | `[from, to]` absolute dates, or rolling `[today + a, today + b]` re-evaluated daily |
| `stay_nights` | `[min, max]`, round trip only |
| `return_by` | optional latest return date |

- Only the departure must fall in the window; the return may fall outside it (28 Nov → 2 Dec satisfies "in November").
- Fixed-date trips are a zero-width window with `min = max`.
- The UI offers presets mapping each phrase in story 2 to this form and always shows the resolved window.

### 5.3 Watch settings

- Passengers: adults count (≥1), configurable. Children/infants out of scope for v1.
- Price threshold: optional, total or per adult (shown both ways).
- Deal sensitivity: % below Baseline, default **30%**.
- Delivery: immediate Alerts or daily Digest; channels email and/or Telegram.
- Active/paused.

### 5.4 Data sources (ADR-0002)

| Source | Produces | Default cadence | Notes |
|---|---|---|---|
| Travelpayouts / Aviasales Data API | Leg prices, Round-trip prices (cached, ≤~48h old) | every 30–60 min | Primary discovery; free; destination wildcard and month queries |
| Ryanair, Wizz public calendar endpoints | Live Leg prices per route per day | every 1–2 h | low request rate; no bot-protection bypass |
| SerpApi Google Flights (free tier, 250/month) | Live round-trip price for a specific itinerary and passenger count | on demand, ~8/day | Verification only |
| Claude agent with web search | Deal context text | per Deal | Optional; never used as a price source |

All sources sit behind one adapter interface: `plan → fetch → raw payload`, and a per-source parser to Leg prices / Round-trip prices. Adding a source does not touch downstream models.

### 5.5 Scan planning

- The **scan planner** turns active Watches into a de-duplicated set of scan tasks (source, origin, destination or wildcard, month), shared across Watches.
- Tasks are prioritised by: proximity of departure, recent price volatility, distance of current best price from a Deal, time since last scan, and source budget (rate limit / monthly quota).
- The planner never exceeds a source's budget; skipped tasks are visible on the data-health page.

### 5.6 Pricing and trip composition (ADR-0001)

- Each Leg price is the cheapest one-way fare per (origin airport, destination airport, date, source, observed_at), normalised to EUR per adult.
- For each Watch, candidate round trips are formed by pairing an outbound Leg price with a return Leg price satisfying the Trip pattern, and comparing with any Round-trip price for the same dates; the cheaper wins and records whether it is a single ticket or two separate tickets.
- One-way Watches use Leg prices directly.

### 5.7 Baseline

- Key: (origin city, destination airport, departure month, stay-nights bucket). Buckets: one-way, 1–2, 3–4, 5–7, 8–14, 15+ nights.
- Statistic: median of daily-minimum prices over a trailing window (default 60 days of observations), with MAD as the spread measure.
- Minimum support: default 20 observations. Below that, fall back to (origin city, destination **country**, month, bucket); below that, no Baseline.
- Cold start: on first ingestion a provisional Baseline is computed from the cross-sectional distribution of prices across all dates in the month, flagged low-confidence.
- Baselines are versioned (computed_at, method, support) so any past Deal can be explained with the Baseline in force at the time.

### 5.8 Deal detection

A composed trip becomes a **Candidate** when:

- its price is ≥ the Watch's sensitivity below the Baseline (default 30%), **and**
- it is under the Price threshold, if the Watch has one.

With no Baseline (cold start, sparse route), a Candidate is created only if the Watch has a Price threshold and the price is under it.

### 5.9 Verification

- Candidates are ranked by % below Baseline and Watch priority; the top ones are verified live in round-trip mode for the Watch's passenger count, within the SerpApi free budget.
- Verified price passes → **Verified Deal**. Fails → discarded and recorded (feeds source-accuracy metrics).
- Budget exhausted → alerted as **Unverified Deal**, clearly labelled.

### 5.10 Alerts

- Channels: email (SMTP) and Telegram bot, behind one notifier interface.
- Deduplication key: (Watch, origin airport, destination airport, outbound date, return date). Re-alert only if the price drops a further ≥10%, or the fare reappears after being absent ≥24h.
- Digest mode batches a Watch's Deals into one daily message.
- Telegram Alerts carry inline 👍/👎 buttons.
- Deal context (optional) is appended when available and never delays the Alert by more than 60 s.

### 5.11 Evaluation

- **Backtest** (dbt model + UI page): for each past Deal, did the price for those dates later return to the Baseline (a real dip) or stay low (a Baseline error or seasonal shift)? Report precision, Alert rate per Watch per week, and the distribution of % below Baseline.
- **Feedback:** 👍/👎 ratings stored per Alert and joined into backtest results.
- Sensitivity and minimum support are tunable per Watch from these results.

### 5.12 UI (Next.js + FastAPI)

| Page | Contents |
|---|---|
| Watches | List; editor with Place picker (search, include/exclude chips, Region tree with resolved airport count), Trip-pattern presets, passengers, threshold, sensitivity, delivery |
| Deals | Feed of Alerts with status, price vs Baseline, booking link, Deal context, 👍/👎 |
| Route explorer | Price history per route and date with Baseline band and observations by source |
| Data health | Source freshness, last successful scan, coverage (routes × months with no data), planner backlog, verification budget used, asset-check failures |
| Backtest | Precision, Alert rate, feedback summary per Watch |

The API reads only from the marts layer.

## 6. Data architecture

```
sources ──► raw (immutable payloads, partitioned by source/date)
              │
              ▼  dbt staging
        Leg prices, Round-trip prices (normalised, EUR, per adult)
              │
              ▼  dbt marts
        price history (change-only, valid_from/valid_to)
        Baselines (versioned)  ◄────── Databricks gold (batch, ADR-0003)
        composed trips → Candidates → Deals → Alerts
              │
              ▼
        FastAPI ─► Next.js UI          notifier ─► email / Telegram
```

- **Orchestration:** Dagster software-defined assets, scheduled per source; sensors trigger composition and detection after each ingestion; partitions by source and date.
- **Raw layer:** every API response stored as received (JSON, compressed) under `raw/source=<s>/dt=<date>/`, so any downstream model can be rebuilt.
- **Change-only history:** consecutive identical observations of a Leg price collapse into one row with a validity interval, cutting stored rows by ~10–50× versus append-everything (~0.5–1M observations/day).
- **Data-quality gates (Dagster asset checks):** e.g. a scan returning zero rows for a normally populated origin, a > X% price-level jump across a whole source, stale source data. A failing check blocks Deal detection for the affected slice.
- **Analytical layer (ADR-0003):** daily export of staging/history as Parquet to a Databricks Free Edition Unity Catalog volume, bronze/silver/gold medallion tables, Baseline recomputation, backtest and seasonality notebooks; results written back to Postgres. Not on the alerting path.
- **dbt portability:** shared models avoid vendor-specific SQL so they run on Postgres and Databricks (and Snowflake, as a documented option).

### Core entities (marts)

`place`, `place_airport` (resolved membership), `watch`, `watch_place` (include/exclude), `scan_task`, `leg_price_history`, `round_trip_price_history`, `baseline`, `candidate`, `verification`, `deal`, `alert`, `alert_feedback`, `source_health`.

## 7. Non-functional requirements

| Area | Requirement |
|---|---|
| Cost | €0/month recurring. |
| Freshness | A Deal is alerted within one scan cycle of its source data arriving (≤ ~60 min for cached sources). |
| Reliability | The pipeline survives any single source failing; Alerts continue on last-known Baselines if Databricks is unavailable. |
| Reproducibility | `docker compose up` on a fresh host brings up the whole operational stack; reference data and Region definitions are versioned in the repo. |
| Access | UI and API bind to localhost on verda and are reached via SSH tunnel. |
| Secrets | API keys, SMTP and Telegram tokens come from environment / `.env`, never committed. |
| Politeness | Each source adapter enforces its own rate limit and backoff; airline adapters are off by default. |
| Testability | Source parsers tested against recorded raw payloads; dbt tests on every model; trip composition and Deal detection covered by unit tests with fixed fixtures. |

## 8. Deployment

Docker Compose on `verda` (4 vCPU, 16 GB): `postgres`, `dagster-webserver`, `dagster-daemon` (code location with dbt), `api` (FastAPI), `web` (Next.js), and a local volume for the raw layer. Databricks Free Edition is reached via its Files and SQL APIs. The public GitHub repository includes a README explaining the cached-discovery-plus-live-verification model and how it mirrors metasearch platforms.

## 9. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Skeleton | Compose stack runs; reference data loaded; Places and Regions resolvable via API |
| M1 | Ingestion | Travelpayouts assets land raw → staging → change-only history with asset checks |
| M2 | Watches & detection | UI Watch editor; trip composition; Baselines (incl. cold start); Candidates |
| M3 | Alerts | Email + Telegram, dedup and Digest; Deals feed in UI |
| M4 | Verification & planning | SerpApi verification within budget; scan planner with priorities; data-health page |
| M5 | Evaluation | Backtest model and page; 👍/👎 feedback loop |
| M6 | Lakehouse | Databricks medallion export, Baseline recompute and backtest jobs, write-back |
| M7 | Extras | Ryanair/Wizz adapters; Deal context agent; README and architecture write-up |

## 10. Risks and known limitations

- **Cached data coverage:** Travelpayouts only knows routes that its users searched recently; obscure routes may have no data. Mitigated by coverage reporting and optional airline adapters.
- **Verification budget:** 250 live checks/month bounds Verified Deals to ~8/day; the rest are labelled Unverified.
- **Single-ticket return blind spot:** a single-ticket return fare on dates no source covered is missed (ADR-0001).
- **Baggage:** prices are not baggage-normalised; low-cost fares may look better than they are.
- **Multi-passenger pricing:** cached prices are per single adult; the real per-person price for N adults may be higher. Handled at Verification only.
- **Source terms:** unofficial airline endpoints may change or forbid access at any time; they are optional and isolated.
- **Databricks Free Edition quotas:** may pause the analytical layer for a day; by design this does not affect Alerts.
