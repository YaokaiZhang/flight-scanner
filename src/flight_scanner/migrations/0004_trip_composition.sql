-- Ticket 04: Round trips composed from Leg prices, and expired Watches.

-- How a Deal's price is ticketed: one_way, single_ticket (one Round-trip price) or
-- separate_tickets (two Leg prices: outbound and return booked independently).
ALTER TABLE app.deals ADD COLUMN ticketing text;
UPDATE app.deals
    SET ticketing = CASE WHEN return_date IS NULL THEN 'one_way' ELSE 'single_ticket' END;
ALTER TABLE app.deals
    ALTER COLUMN ticketing SET NOT NULL,
    ADD CONSTRAINT deals_ticketing_check
        CHECK (ticketing IN ('one_way', 'single_ticket', 'separate_tickets'));

-- A Watch whose departure window has fully passed is marked expired and generates no demand.
ALTER TABLE app.watches DROP CONSTRAINT watches_status_check;
ALTER TABLE app.watches
    ADD CONSTRAINT watches_status_check CHECK (status IN ('active', 'paused', 'expired'));
