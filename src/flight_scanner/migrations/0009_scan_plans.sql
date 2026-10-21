-- Scan planner (ticket 09): every pipeline run plans one scan per source and records each scan
-- task, whether it was scheduled (then scanned or failed) or skipped over the source's budget.
-- Numbered 0009 so parallel tickets' migrations do not collide.
CREATE TABLE app.scan_plans (
    id          bigserial PRIMARY KEY,
    planned_at  timestamptz NOT NULL
);

CREATE TABLE app.scan_tasks (
    id                  bigserial PRIMARY KEY,
    plan_id             bigint      NOT NULL REFERENCES app.scan_plans (id) ON DELETE CASCADE,
    source              text        NOT NULL,
    origin              text        NOT NULL,
    destination         text,                  -- null: wildcard (anywhere from origin)
    month               date        NOT NULL,  -- first day of the departure month
    round_trip          boolean     NOT NULL,  -- also ask for single-ticket Round-trip prices
    earliest_departure  date        NOT NULL,
    destinations        integer     NOT NULL,  -- demanded destination airports it covers
    watch_ids           bigint[]    NOT NULL,
    priority            numeric     NOT NULL,
    factors             jsonb       NOT NULL,
    requests            jsonb       NOT NULL,  -- the source requests (params) it costs
    status              text        NOT NULL
        CHECK (status IN ('scheduled', 'scanned', 'failed', 'skipped')),
    reason              text,
    finished_at         timestamptz
);
CREATE INDEX scan_tasks_plan ON app.scan_tasks (plan_id);
CREATE INDEX scan_tasks_last_scan ON app.scan_tasks (source, origin, destination, month)
    WHERE status = 'scanned';
