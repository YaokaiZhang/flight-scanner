-- Ticket 14: optional Deal context ("why is this cheap?") from web research.
-- deal_context_status is null until the Deal was researched (once, before its first Alert):
--   found  = a context line was produced     none   = the researcher had nothing to say
--   late   = not ready within the cap; Alerts went out without it     failed = researcher error
ALTER TABLE app.deals
    ADD COLUMN deal_context text,
    ADD COLUMN deal_context_status text
        CHECK (deal_context_status IN ('found', 'none', 'late', 'failed')),
    ADD COLUMN deal_context_at timestamptz;
