-- Ticket 03: per-Watch sensitivity (how far below the Baseline a fare must be, in percent).
ALTER TABLE app.watches
    ADD COLUMN sensitivity_pct integer NOT NULL DEFAULT 30 CHECK (sensitivity_pct BETWEEN 1 AND 90);
