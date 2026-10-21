-- Ticket 07: Alert dedup, re-alerts and Digests.

-- Per-Watch delivery: an immediate Alert per Deal, or one daily Digest.
ALTER TABLE app.watches
    ADD COLUMN delivery text NOT NULL DEFAULT 'immediate'
        CHECK (delivery IN ('immediate', 'digest'));

-- A Deal tracks whether its fare is still a Candidate and which Alert round is due.
--   last_seen_at          last scan at which the dedup key was a Candidate
--   absent_since          first scan at which it was no longer a Candidate (null while present)
--   alert_round           1 for the first Alert; +1 on each further drop or reappearance
--   alert_price_total_eur the price the current round alerts on (the "last alerted price")
--   alert_due_at          when the current round became due (Digests collect rounds by this)
ALTER TABLE app.deals
    ADD COLUMN last_seen_at timestamptz,
    ADD COLUMN absent_since timestamptz,
    ADD COLUMN alert_round integer NOT NULL DEFAULT 1,
    ADD COLUMN alert_price_total_eur numeric(10, 2),
    ADD COLUMN alert_due_at timestamptz;
UPDATE app.deals
   SET last_seen_at = detected_at, alert_price_total_eur = price_total_eur, alert_due_at = detected_at;
ALTER TABLE app.deals
    ALTER COLUMN last_seen_at SET NOT NULL,
    ALTER COLUMN alert_price_total_eur SET NOT NULL,
    ALTER COLUMN alert_due_at SET NOT NULL;

-- One Digest message per (Watch, channel) and day.
CREATE TABLE app.digests (
    id          bigserial PRIMARY KEY,
    watch_id    bigint      NOT NULL REFERENCES app.watches (id) ON DELETE CASCADE,
    channel     text        NOT NULL,
    sent_at     timestamptz NOT NULL,
    deal_count  integer     NOT NULL
);

-- An Alert row is one Deal round delivered on one channel, immediately or inside a Digest.
ALTER TABLE app.alerts
    ADD COLUMN alert_round integer NOT NULL DEFAULT 1,
    ADD COLUMN digest_id bigint REFERENCES app.digests (id) ON DELETE CASCADE;
CREATE INDEX alerts_deal_channel_round ON app.alerts (deal_id, channel, alert_round);
