-- Whether a Watch's Price threshold must hold together with the Baseline test ("both") or is
-- enough on its own, as is the Baseline test ("either").
ALTER TABLE app.watches
    ADD COLUMN price_threshold_match text CHECK (price_threshold_match IN ('both', 'either'));
UPDATE app.watches SET price_threshold_match = 'both' WHERE price_threshold_eur IS NOT NULL;
