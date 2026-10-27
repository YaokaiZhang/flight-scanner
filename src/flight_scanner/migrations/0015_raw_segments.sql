-- The raw store's segments copied to the archive (raw_archive.py), with the size uploaded: a
-- segment is uploaded again if it grew since, and pruned locally only while the sizes match.
CREATE TABLE landing.raw_segments (
    path         text        PRIMARY KEY,  -- relative to the raw store root
    bytes        bigint      NOT NULL,
    archived_at  timestamptz NOT NULL
);
