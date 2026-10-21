-- Airline adapters (ticket 13): a source that turned us away (bot protection, access denied)
-- disables itself until the owner re-enables it (`python -m flight_scanner unblock <source>`).
-- Ticket 10's data-health page shows these rows (GET /sources/blocked).
CREATE TABLE app.source_blocks (
    source      text        PRIMARY KEY,
    blocked_at  timestamptz NOT NULL,
    reason      text        NOT NULL
);
