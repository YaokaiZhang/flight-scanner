-- Ticket 08: Verification and Price insights.

-- Price insights parsed from Verification answers (one per payload): a source's typical price
-- range for one trip, for `adults` passengers in `currency` (dbt staging normalises to EUR per
-- adult). The insight's price-history points land in leg_prices / round_trip_prices.
CREATE TABLE landing.price_insights (
    payload_id      bigint      NOT NULL REFERENCES landing.raw_payloads (id),
    source          text        NOT NULL,
    observed_at     timestamptz NOT NULL,
    origin          text        NOT NULL,
    destination     text        NOT NULL,
    departure_date  date        NOT NULL,
    return_date     date,
    adults          integer     NOT NULL DEFAULT 1,
    currency        text        NOT NULL,
    typical_low     numeric(10, 2) NOT NULL,
    typical_high    numeric(10, 2) NOT NULL,
    lowest_price    numeric(10, 2),
    price_level     text,
    history_points  integer     NOT NULL DEFAULT 0
);

-- A Deal's Verification outcome for its current Alert round:
--   verified   = checked live and still a Deal (Alerts carry the live price)
--   failed     = checked live and not a Deal (or not found): recorded, never alerted
--   unverified = not checked (budget spent, no verifier, verifier outage): alerted, labelled
-- verification_round = the Alert round the outcome belongs to (null: not judged yet).
ALTER TABLE app.deals DROP CONSTRAINT deals_verification_check;
ALTER TABLE app.deals
    ADD CONSTRAINT deals_verification_check
        CHECK (verification IN ('verified', 'unverified', 'failed')),
    ADD COLUMN verification_round        integer,
    ADD COLUMN verification_reason       text,
    ADD COLUMN verified_at               timestamptz,
    ADD COLUMN verified_price_total_eur  numeric(10, 2);

-- Every Verification decision (append-only), for quota accounting and source accuracy.
-- `called` = a live request was spent on it (counts against the source's quota).
CREATE TABLE app.verifications (
    id                          bigserial PRIMARY KEY,
    deal_id                     bigint      NOT NULL REFERENCES app.deals (id) ON DELETE CASCADE,
    alert_round                 integer     NOT NULL,
    checked_at                  timestamptz NOT NULL,
    source                      text,
    called                      boolean     NOT NULL,
    outcome                     text        NOT NULL
        CHECK (outcome IN ('verified', 'unverified', 'failed')),
    reason                      text        NOT NULL,
    payload_id                  bigint REFERENCES landing.raw_payloads (id),
    cached_price_per_adult_eur  numeric(10, 2) NOT NULL,
    live_price_per_adult_eur    numeric(10, 2),
    baseline_tier               text,
    baseline_per_adult_eur      numeric(10, 2)
);
CREATE INDEX verifications_quota ON app.verifications (source, checked_at) WHERE called;

-- Deals that existed before Verification keep their outcome for the rounds already alerted.
UPDATE app.deals SET verification_round = alert_round;
