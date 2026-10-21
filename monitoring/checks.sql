-- RALI monitoring checks
-- Run after dbt build, with psql or the Supabase SQL editor:
--   psql "$SUPABASE_URL" -f monitoring/checks.sql
--
-- The file is intentionally runnable as-is. Section 1 writes a small snapshot
-- row per object so that "versus the previous run" has a real baseline. The
-- remaining sections are read-only.

CREATE SCHEMA IF NOT EXISTS monitoring;

CREATE TABLE IF NOT EXISTS monitoring.run_snapshots (
    run_id       bigint      NOT NULL,
    captured_at  timestamptz NOT NULL DEFAULT now(),
    object_name  text        NOT NULL,
    row_count    bigint      NOT NULL,
    PRIMARY KEY (run_id, object_name)
);

CREATE SEQUENCE IF NOT EXISTS monitoring.run_id_seq;

-- 1. Snapshot row counts for the tables whose volume is a pipeline signal.
WITH this_run AS (
    SELECT nextval('monitoring.run_id_seq') AS run_id
),
counts AS (
    SELECT 'raw.osm_restaurants' AS object_name, count(*) AS row_count
    FROM raw.osm_restaurants
    UNION ALL
    SELECT 'raw.website_signals', count(*) FROM raw.website_signals
    UNION ALL
    SELECT 'raw.lifecycle_events', count(*) FROM raw.lifecycle_events
    UNION ALL
    SELECT 'intermediate.int_account_deduped', count(*) FROM intermediate.int_account_deduped
    UNION ALL
    SELECT 'marts.dim_account', count(*) FROM marts.dim_account
)
INSERT INTO monitoring.run_snapshots (run_id, object_name, row_count)
SELECT this_run.run_id, counts.object_name, counts.row_count
FROM this_run CROSS JOIN counts;

-- 1a. Row-count spike/drop versus the previous run. Alert at >20% either way.
-- A drop is the dangerous case: an HTTP-200 partial extract still loads.
WITH ranked AS (
    SELECT object_name,
           run_id,
           captured_at,
           row_count,
           lag(row_count) OVER (PARTITION BY object_name ORDER BY run_id) AS prev_count
    FROM monitoring.run_snapshots
),
latest AS (
    SELECT DISTINCT ON (object_name) *
    FROM ranked
    ORDER BY object_name, run_id DESC
)
SELECT object_name,
       prev_count,
       row_count,
       round(((row_count - prev_count)::numeric / nullif(prev_count, 0)) * 100, 1) AS pct_change,
       'ALERT: source row count moved more than 20%' AS finding
FROM latest
WHERE prev_count IS NOT NULL
  AND abs((row_count - prev_count)::numeric / nullif(prev_count, 0)) > 0.20
ORDER BY object_name;

-- 1b. Account-count collapse versus the previous run. Alert at >5% drop.
-- This is the over-merge alarm; pair it with the source_record_count diagnostic.
WITH ranked AS (
    SELECT run_id,
           row_count,
           lag(row_count) OVER (ORDER BY run_id) AS prev_count
    FROM monitoring.run_snapshots
    WHERE object_name = 'intermediate.int_account_deduped'
),
latest AS (
    SELECT * FROM ranked ORDER BY run_id DESC LIMIT 1
)
SELECT prev_count,
       row_count,
       round(((row_count - prev_count)::numeric / nullif(prev_count, 0)) * 100, 1) AS pct_change,
       'ALERT: account count fell more than 5%; inspect source_record_count for over-merging' AS finding
FROM latest
WHERE prev_count IS NOT NULL
  AND (row_count - prev_count)::numeric / nullif(prev_count, 0) < -0.05;

-- 2. Territory/full-address drift. Territory is never null, so Unknown is
-- checked separately; a null-only check would miss the 17.8% Unknown bucket.
SELECT
    round(avg((territory IS NULL)::int)::numeric, 4)        AS territory_null_rate,
    round(avg((territory = 'Unknown')::int)::numeric, 4)    AS territory_unknown_rate,
    round(avg((full_address IS NULL)::int)::numeric, 4)     AS full_address_null_rate,
    CASE
        WHEN avg((territory IS NULL)::int) > 0.10
          OR avg((territory = 'Unknown')::int) > 0.10
          OR avg((full_address IS NULL)::int) > 0.10
        THEN 'ALERT: territory unknown or full_address null above 10%'
        ELSE 'ok'
    END AS finding
FROM marts.dim_account;

-- 3. Freshness of website signals. Alert if the newest fetch is older than 7 days.
SELECT max(fetched_at)                    AS latest_fetch,
       now() - max(fetched_at)            AS age,
       CASE
           WHEN max(fetched_at) IS NULL THEN 'ALERT: no website signals loaded'
           WHEN now() - max(fetched_at) > interval '7 days' THEN 'ALERT: signals older than 7 days'
           ELSE 'ok'
       END AS finding
FROM raw.website_signals;

-- 4. Duplicate dedup keys. Must be zero; a non-zero value means the model
-- emitted more than one row per account key.
SELECT count(*) - count(DISTINCT dedup_key) AS duplicate_rows,
       CASE
           WHEN count(*) - count(DISTINCT dedup_key) > 0 THEN 'ALERT: duplicate dedup_key'
           ELSE 'ok'
       END AS finding
FROM intermediate.int_account_deduped;

-- 5. Orphan lifecycle events. Must be zero.
SELECT count(*) AS orphan_events,
       CASE
           WHEN count(*) > 0 THEN 'ALERT: lifecycle events without a dim_account row'
           ELSE 'ok'
       END AS finding
FROM marts.fct_lifecycle_event e
LEFT JOIN marts.dim_account a USING (account_id)
WHERE a.account_id IS NULL;

-- 6. Out-of-order lifecycle timestamps. Order by stage rank, not by the
-- timestamp itself, or the check would be tautological.
WITH staged AS (
    SELECT account_id,
           event_name,
           event_timestamp,
           CASE event_name
               WHEN 'prospect_created' THEN 1
               WHEN 'demo_booked'      THEN 2
               WHEN 'closed_won'       THEN 3
               WHEN 'onboarded'        THEN 4
               WHEN 'first_order'      THEN 5
               WHEN '30_day_active'    THEN 6
               WHEN 'support_ticket'   THEN 7
               WHEN 'renewal_due'      THEN 8
               ELSE 99
           END AS stage_rank
    FROM marts.fct_lifecycle_event
),
ordered AS (
    SELECT account_id,
           event_name,
           event_timestamp,
           lag(event_timestamp) OVER (
               PARTITION BY account_id ORDER BY stage_rank, event_timestamp
           ) AS prev_timestamp
    FROM staged
)
SELECT count(*) AS out_of_order_events,
       CASE
           WHEN count(*) > 0 THEN 'ALERT: event timestamps violate stage order'
           ELSE 'ok'
       END AS finding
FROM ordered
WHERE prev_timestamp IS NOT NULL
  AND event_timestamp < prev_timestamp;

-- 7. Duplicate (account_id, event_name) pairs. Must be zero; a non-zero value
-- usually means an incremental delete+insert missed a batch.
SELECT count(*) AS duplicate_event_pairs,
       CASE
           WHEN count(*) > 0 THEN 'ALERT: duplicate account/event pairs'
           ELSE 'ok'
       END AS finding
FROM (
    SELECT account_id, event_name
    FROM marts.fct_lifecycle_event
    GROUP BY account_id, event_name
    HAVING count(*) > 1
) d;

-- 8. Warehouse objects must not appear in public. Supabase exposes public via
-- the Data API; this is the schema-macro regression check.
SELECT count(*) AS public_tables,
       CASE
           WHEN count(*) > 0 THEN 'ALERT: warehouse table found in public'
           ELSE 'ok'
       END AS finding
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE';

-- Optional pg_cron schedule. pg_cron cannot execute a .sql file directly, so
-- wrap these statements in a function (monitoring.run_checks()) first, then:
--
--   select cron.schedule(
--       'rali-monitoring',
--       '0 6 * * *',
--       $$select monitoring.run_checks();$$
--   );


-- 9. Signal coverage. Alert if fewer than half of accounts have a confirmed
-- homepage fingerprint. Unknown is not the same as observed-absent.
SELECT
    round(100.0 * avg((signal_confidence = 'confirmed')::int), 1) AS confirmed_pct,
    count(*) FILTER (WHERE signal_confidence = 'unknown_unreachable') AS unknown_unreachable,
    count(*) FILTER (WHERE signal_confidence = 'unknown_no_match') AS unknown_no_match,
    CASE
        WHEN avg((signal_confidence = 'confirmed')::int) < 0.50
        THEN 'ALERT: less than half of accounts have confirmed signals'
        ELSE 'ok'
    END AS finding
FROM marts.dim_account;

-- 10. Fit score range. A rules score outside 0-100 means the rubric or the
-- source signals changed under the model.
SELECT
    min(fit_score) AS min_fit,
    max(fit_score) AS max_fit,
    count(*) FILTER (WHERE fit_score < 0 OR fit_score > 100) AS out_of_range,
    CASE
        WHEN count(*) FILTER (WHERE fit_score < 0 OR fit_score > 100) > 0
        THEN 'ALERT: fit_score outside 0-100'
        ELSE 'ok'
    END AS finding
FROM marts.dim_account;

-- 11. Queue reconciliation. The sales queue should equal independent accounts;
-- the CS queue should equal onboarded accounts.
SELECT
    (SELECT count(*) FROM marts.mart_sales_queue) AS sales_rows,
    (SELECT count(*) FROM marts.dim_account WHERE NOT is_chain) AS independent_accounts,
    (SELECT count(*) FROM marts.mart_cs_queue) AS cs_rows,
    (SELECT count(*) FROM marts.fct_account_health WHERE has_onboarded) AS onboarded_accounts,
    (SELECT count(*) FROM marts.mart_cs_queue WHERE is_at_risk) AS at_risk_rows,
    CASE
        WHEN (SELECT count(*) FROM marts.mart_sales_queue)
             <> (SELECT count(*) FROM marts.dim_account WHERE NOT is_chain)
          OR (SELECT count(*) FROM marts.mart_cs_queue)
             <> (SELECT count(*) FROM marts.fct_account_health WHERE has_onboarded)
        THEN 'ALERT: queue row counts do not reconcile'
        ELSE 'ok'
    END AS finding;
