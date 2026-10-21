-- Ticket 06: full Alert content, per-Watch channels, and 👍/👎 feedback.

-- Where a Watch's Alerts go. Notifiers for other channels (log, recording) get every Alert.
ALTER TABLE app.watches
    ADD COLUMN channels text[] NOT NULL DEFAULT '{email,telegram}'
        CHECK (cardinality(channels) >= 1 AND channels <@ '{email,telegram}');

-- Deal details an Alert shows. Nullable where the pipeline may not know them (yet):
-- baseline_per_adult_eur stays null until a Baseline exists; booking_url falls back to a
-- Google Flights search link built from the route and dates.
ALTER TABLE app.deals
    ADD COLUMN airlines               text,
    ADD COLUMN stops                  integer,  -- most stops in any one direction
    ADD COLUMN travel_minutes         integer,  -- total time in the air and connecting, all legs
    ADD COLUMN separate_tickets       boolean NOT NULL DEFAULT false,
    ADD COLUMN booking_url            text,
    ADD COLUMN baseline_per_adult_eur numeric(10, 2);

-- 👍/👎 on a Deal, from Telegram (against the Alert that carried the buttons) or the Deals feed.
-- Append-only; the latest row per Deal is its current rating (rating null = cleared).
CREATE TABLE app.deal_feedback (
    id          bigserial PRIMARY KEY,
    deal_id     bigint      NOT NULL REFERENCES app.deals (id) ON DELETE CASCADE,
    alert_id    bigint      REFERENCES app.alerts (id) ON DELETE SET NULL,
    rating      text        CHECK (rating IN ('up', 'down')),
    via         text        NOT NULL CHECK (via IN ('telegram', 'web')),
    created_at  timestamptz NOT NULL
);
CREATE INDEX deal_feedback_by_deal ON app.deal_feedback (deal_id, created_at DESC, id DESC);

-- Small per-notifier cursors (e.g. the Telegram getUpdates offset).
CREATE TABLE app.notifier_state (
    name   text  PRIMARY KEY,
    value  jsonb NOT NULL
);
