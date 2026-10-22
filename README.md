# Flight Scanner

A personal, self-hosted flight-price scanner. You describe trips you'd take as **Watches**
("Helsinki or Tallinn to anywhere in Europe except Sweden, 3–6 nights in November"). It collects
prices from free, cached sources, learns what each trip normally costs (its **Baseline**) and
sends an **Alert** by email or Telegram when a fare is well below that: a **Deal**. It doesn't
just fire when a fare drops under a fixed number.

The vocabulary (Watch, Place, Trip pattern, Baseline, Candidate, Deal, Verification, Alert,
Digest) is defined in [CONTEXT.md](CONTEXT.md). The product brief is [docs/PRD.md](docs/PRD.md) and
the v1 spec and its tickets are in [docs/work/flight-scanner/](docs/work/flight-scanner/spec.md).

## How it works

```
sources ──► landing (raw payloads + parsed rows) ──► dbt: staging → history → baselines → marts
 (Travelpayouts,                                                           │
  Ryanair, Wizz,       Watches (UI/API) ──► scan planner                   ▼
  fake replay)                                         Candidates ──► Deals ──► Verification
                                                                               (SerpApi, budgeted)
                                                                                    │
                                    Deal context (optional Claude line) ◄───────────┤
                                                                                    ▼
                                                           Alerts / Digests (email, Telegram, log)
```

- **Dagster** runs the scan every 30 minutes (`scan` job) and the optional Databricks
  `lakehouse` job daily at 04:15 Helsinki time. Telegram 👍/👎 feedback is read by a sensor.
- **Postgres** holds everything: app tables (`app`), parsed source rows (`landing`) and the dbt
  models (`staging`, `marts`, `analytics`). Migrations apply automatically on startup.
- **FastAPI** (`flight_scanner.api`) serves Watches, Places, Deals, routes and price history,
  data health and the backtest.
- **Next.js** (`web/`) is the UI: Watches, Deals, Routes, Data health and Backtest. It proxies the
  API under `/api`, so only one port has to be reachable.
- Architecture decisions are in [docs/adr/](docs/adr/): Round trips composed from Leg prices,
  free cached-first sources with budgeted Verification, and the operational loop on one server
  with the analytical layer on Databricks Free Edition.

## Quick start

```sh
cp .env.example .env      # then edit it: sources, tokens, notifiers
scripts/start.sh          # start everything; prints the URLs
```

[`scripts/start.sh`](scripts/start.sh) starts Postgres, the API, the Dagster webserver and
daemon, and the UI, then waits until each one answers:

| Command | What it does |
| --- | --- |
| `scripts/start.sh` or `up` | Start the stack (idempotent) |
| `scripts/start.sh scan` | Run one scan now instead of waiting for the half-hour schedule |
| `scripts/start.sh status` | Show what is running |
| `scripts/start.sh logs [service]` | Follow a service's log (`api`, `dagster-webserver`, `dagster-daemon`, `web`, `postgres`) |
| `scripts/start.sh down` | Stop everything (data is kept) |

| Service | URL |
| --- | --- |
| UI | http://127.0.0.1:3000 |
| Dagster | http://127.0.0.1:3001 |
| API | http://127.0.0.1:8000 (`/health`, `/docs`) |

Everything binds to 127.0.0.1 only. From another machine, use an SSH tunnel:
`ssh -L 3000:127.0.0.1:3000 -L 3001:127.0.0.1:3001 <host>`.

It picks one of two modes automatically. Set `FS_MODE=docker` or `FS_MODE=local` to choose.

### Docker mode (the server deployment)

This is used when `docker compose` is available. It runs [compose.yaml](compose.yaml): Postgres 16
with a volume, one Python image for the API and Dagster, and the UI image. `.env` is passed to
every container, and the script refuses to start while `POSTGRES_PASSWORD` is still `change-me`.

### Local mode (no Docker)

This is for a laptop or a shared login node. It needs PostgreSQL 16 (`initdb`, `pg_ctl`), Python
3.12 with [uv](https://docs.astral.sh/uv/), Node 22 and curl on `PATH`. On roihu, run
`conda activate flight-scanner` first.

- **Postgres** is a private cluster that listens only on a unix socket in the state directory,
  with owner-only permissions. Nobody else on the host can connect, so it needs no password.
- **Python and UI dependencies** are installed with `uv sync` and `npm ci`. The UI is rebuilt
  when its sources change.
- **Dagster** keeps its own run history in SQLite, with at most one run at a time, as in Docker.
- **State** goes in `FS_STATE_DIR` (default `.local/`): the database, raw payloads, Dagster
  storage, logs and pid files. On a node-local disk, use for example
  `FS_STATE_DIR=/tmp/$USER-flight-scanner`.
- **Ports** are set with `FS_WEB_PORT`, `FS_API_PORT` and `FS_DAGSTER_PORT`. Change them on a
  shared host where the defaults are taken. Note that other users on the same host can reach
  127.0.0.1 ports, and the API has no login.

### Trying it without API keys

The `fake` source replays saved payloads, so you can see the full pipeline with no accounts:

```sh
FS_SOURCES=fake
FS_FAKE_PAYLOAD_DIR=/absolute/path/to/tests/fixtures/payloads/fake
```

Create a Watch in the UI (for example HEL to BCN in November), then run `scripts/start.sh scan`.

## Configuration

Every setting and secret comes from the environment. [.env.example](.env.example) lists each
one with an explanation. In short:

| Area | Variables | Default |
| --- | --- | --- |
| Sources | `FS_SOURCES` (`travelpayouts`, `fake`, `ryanair`, `wizz`), `TRAVELPAYOUTS_TOKEN`, `FS_SCAN_BUDGETS` | none enabled |
| Alerts | `FS_NOTIFIERS` (`log`, `email`, `telegram`), `SMTP_*`, `ALERT_EMAIL_*`, `TELEGRAM_*` | `log` |
| Verification | `FS_VERIFIER=serpapi`, `SERPAPI_API_KEY` | off: Deals are alerted *Unverified* |
| Deal context | `FS_DEAL_CONTEXT=claude`, `ANTHROPIC_API_KEY` | off |
| Ryanair / Wizz | `FS_ENABLE_RYANAIR`, `FS_ENABLE_WIZZ`, plus listing them in `FS_SOURCES` | off |
| Databricks | `FS_LAKEHOUSE=databricks`, `DATABRICKS_*`, `FS_DATABRICKS_*` | off |

The Verification budget is 8 searches a day and 250 a month, which is SerpApi's free tier.

The Ryanair and Wizz adapters read the airlines' unofficial public fare calendars. Both airlines'
terms forbid automated access, so read the note in `.env.example` before turning them on. If a
site turns an adapter away, it disables itself and shows under `GET /sources/blocked`. Re-enable
it with `python -m flight_scanner unblock ryanair` (or `wizz`).

The Databricks analytical layer needs a one-time setup, described in
[databricks/README.md](databricks/README.md).

## One-off commands

These run with the same environment as the services. In local mode that means after
`scripts/start.sh up`, using `.venv/bin/python` and `POSTGRES_HOST` pointing at the state dir's
`pg-socket`. In Docker mode, run them through `docker compose exec dagster-daemon …`.

```sh
python -m flight_scanner migrate            # apply pending migrations
python -m flight_scanner scan               # one scan now
python -m flight_scanner rebuild            # re-parse every raw payload and rebuild the dbt models
python -m flight_scanner lakehouse          # run the Databricks job now
python -m flight_scanner unblock <source>   # re-enable a blocked airline adapter
```

## Development

```sh
uv sync                                  # Python 3.12 deps, including dev tools
uv run ruff check .
uv run pytest tests -n 4                 # about 9 minutes on 4 cores; each test session starts its own Postgres
cd web && npm ci && npm run typecheck && npm run build
cd web && npx playwright install chromium && npm run test:e2e
```

- **Postgres in tests:** the tests need `initdb` and `pg_ctl` on `PATH`. Each session starts a
  throwaway cluster and gives every test a cloned database, so parallel runs never collide.
- **Test layers:** `tests/seam1` drives whole scans through a test harness (fixed clock, replayed
  payloads, recording notifiers). `tests/seam2` covers the HTTP API. `tests/seam3` holds the
  contract tests for each external service: Travelpayouts, Ryanair, Wizz, SerpApi, Claude and
  Databricks. Payload fixtures live in `tests/fixtures/payloads/`.
- **Speed:** harness scans skip dbt's data tests. `test_scans_pass_every_dbt_data_test` keeps
  them covered, and `h.run_dbt_data_tests()` turns them on in a test.
- **Playwright** starts its own backend (`python -m flight_scanner.testing.e2e_stack`) and the UI
  on random ports.

### Layout

```
src/flight_scanner/
  sources/        source adapters (Travelpayouts, Ryanair, Wizz, SerpApi, replay) and the polite HTTP client
  pipeline/       Dagster definitions, the shared runtime, the dbt plumbing
  places/         reference data (airports, cities, countries, Regions) and Place resolution
  notify/         Alert channels (email, Telegram, log) and message content
  lakehouse/      Parquet export and the Databricks job client
  deal_context/   optional Claude "why is this cheap?" researcher
  api/            FastAPI app
  migrations/     plain SQL, applied in order
  testing/        test harness, fakes, ephemeral Postgres, e2e backend
dbt/              staging → history → baselines → marts and backtest models (Postgres and Databricks)
databricks/       Databricks asset bundle and the medallion SQL
web/              Next.js UI and Playwright tests
docker/           images and Dagster config for Compose
docs/             PRD, ADRs, design notes, spec and tickets
```

## What is not verified yet

These parts are built from public documentation and tested against fakes. None has been run
against the real service:

- **Ryanair and Wizz:** the response formats of their fare-calendar endpoints are unconfirmed,
  and Wizz is likely to block automated requests.
- **SerpApi:** prices are assumed to be totals for the whole party.
- **Databricks:** nothing has been deployed yet. How the free tier reports a spent quota is a
  guess, and nobody has checked that Spark computes the same Baselines as Postgres.
