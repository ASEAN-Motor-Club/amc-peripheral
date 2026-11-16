-- Workshop source-side read indexes.
--
-- Apply after each scraper schema migration and before starting the web service.
-- ANALYZE is mandatory: with the old single-column indexes left in place SQLite
-- otherwise costs a full public sort as cheaper and never selects these covering
-- indexes.
--
-- The predicates use the same expressions as queries.PUBLIC_WHERE. Keep them in
-- sync if that filter changes.

CREATE INDEX IF NOT EXISTS ix_ws_site_popular ON workshop (
    COALESCE(installed, 0) DESC,
    COALESCE(votes, 0) DESC,
    id DESC
)
WHERE deleted_at IS NULL AND COALESCE(hidden, 0) = 0 AND account_id > 0;

CREATE INDEX IF NOT EXISTS ix_ws_site_new ON workshop (
    created_at DESC,
    id DESC
)
WHERE deleted_at IS NULL AND COALESCE(hidden, 0) = 0 AND account_id > 0;

CREATE INDEX IF NOT EXISTS ix_ws_site_vehicle_popular ON workshop (
    vehicle_key,
    COALESCE(installed, 0) DESC,
    COALESCE(votes, 0) DESC,
    id DESC
)
WHERE deleted_at IS NULL AND COALESCE(hidden, 0) = 0 AND account_id > 0;

CREATE INDEX IF NOT EXISTS ix_ws_site_vehicle_new ON workshop (
    vehicle_key,
    created_at DESC,
    id DESC
)
WHERE deleted_at IS NULL AND COALESCE(hidden, 0) = 0 AND account_id > 0;

CREATE INDEX IF NOT EXISTS ix_ws_site_account_new ON workshop (
    account_id,
    created_at DESC,
    id DESC
)
WHERE deleted_at IS NULL AND COALESCE(hidden, 0) = 0 AND account_id > 0;

CREATE INDEX IF NOT EXISTS ix_ws_site_account_popular ON workshop (
    account_id,
    COALESCE(installed, 0) DESC,
    COALESCE(votes, 0) DESC,
    id DESC
)
WHERE deleted_at IS NULL AND COALESCE(hidden, 0) = 0 AND account_id > 0;

ANALYZE;
