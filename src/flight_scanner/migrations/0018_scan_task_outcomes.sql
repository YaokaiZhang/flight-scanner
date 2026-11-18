-- Each source's latest finished task, which data health and the stall alert read every few
-- minutes. Only scanned and failed tasks get finished_at, so this skips the skipped ones that
-- make up most of the table. On a large live table, build it first with CREATE INDEX
-- CONCURRENTLY under this name, and this is a no-op.
CREATE INDEX IF NOT EXISTS scan_tasks_outcome ON app.scan_tasks (source, status, finished_at)
    WHERE finished_at IS NOT NULL;
