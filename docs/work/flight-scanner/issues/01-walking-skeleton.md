# 01: Walking skeleton: one fixed-date Watch to one Alert

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** The thinnest end-to-end path through the whole system. The owner opens the UI over an SSH tunnel, creates a one-way, fixed-date Watch (e.g. HEL→BCN on a given date, 1 adult) with a Price threshold, and when a source reports a Leg price under the threshold, a Deal appears in the Deals feed and an Alert is handed to the notifier. Sources and notifier are fakes at this stage; this ticket establishes the stack, the repository and the test harness every later ticket builds on.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The project folder on verda is a git repository with an initial commit including the existing docs.
- [ ] One command brings up the operational stack on a fresh host: Postgres, Dagster (webserver and daemon), the HTTP API and the web UI; UI and API bind to localhost only.
- [ ] All secrets come from environment variables; an example env file is committed, a real one is not.
- [ ] The source-adapter interface (plan → fetch → parse into Leg prices / Round-trip prices) exists, with a fake adapter that replays recorded payloads scripted per scan time.
- [ ] The notifier interface exists, with a recording fake.
- [ ] An injectable clock is used everywhere time matters.
- [ ] Seam-1 harness: a test can create a Watch, advance the clock, run the pipeline in-process against real Postgres and assert on recorded Alerts.
- [ ] Seam-1 test: a Leg price under the threshold yields exactly one Alert; one above it yields none.
- [ ] Seam-2 test: create, read and list Watches over HTTP.
- [ ] Playwright smoke test: create the Watch in the UI and see the Deal in the Deals feed.
- [ ] Raw payloads are stored immutably, partitioned by source and date, from the first ingestion onward.
