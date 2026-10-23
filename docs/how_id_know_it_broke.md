# How I'd know it broke

A pipeline that only reports "success" is not monitored; it is announced. Each check in `monitoring/checks.sql` exists because a specific failure has a shape. The checks run after a load; the optional `pg_cron` block is a convenience.

The figures below describe the documented Dallas run from October 21–22, 2026. The checks query the warehouse at run time; these examples are not fixed targets.

**1. Row count per source table versus the previous run.** Alert above 20% movement in either direction. A drop is the dangerous case: Overpass can return HTTP 200 with a truncated payload, and `COPY` will load it. The marts still build on half the market. A spike is usually a scope change that should be visible.

**2. Territory, Unknown territory, and full-address drift.** Alert when any is above 10%. `territory` is never null, so a null-only check misses the 665 Dallas accounts (45.0%) in `Unknown`; `full_address` is null for 28.3%. Those are known coverage gaps, not silent failures, so the check surfaces them rather than hiding them.

**3. Freshness of `raw.website_signals`.** Alert when `max(fetched_at)` is older than 7 days. The fingerprint job can fail domain-by-domain and still exit zero. Stale signals are worse than missing ones because a rep reads “no online ordering” as a current fact.

**4. Duplicate dedup keys and account-count collapse.** `count(*) - count(distinct dedup_key)` must be zero; the account count must not fall more than 5% versus the prior snapshot. A 5% drop is not normal churn; it usually means an address normalization merged distinct tenants. `source_record_count` is the diagnostic.

**5. Orphaned lifecycle events.** Any `fct_lifecycle_event.account_id` without a `dim_account` row is a failure, not a warning. The generator and dimension disagreed, or a rebuild ran out of order; queue joins would silently drop those accounts.

**6. Out-of-order timestamps and duplicate `(account_id, event_name)` pairs.** Both must be zero. The first catches a generator state bug; the second catches an incremental load that failed to delete the prior batch. `tests/assert_lifecycle_stage_order.sql` enforces the same rule in dbt.

**7. Empty `public` schema.** Alert if any base table appears in `public`. Supabase exposes that schema to the Data API; this is the regression check for the schema-naming macro. It should page, not wait for review.

**8. dbt tests.** Unique/not-null keys, relationships from events and health to `dim_account`, accepted event/status values, the funnel `(account_id, event_name)` uniqueness, score ranges, and the custom `between` test. A failed test blocks the build; monitoring is for the things that can be wrong even when every test passes.

**9. Signal coverage.** Alert when fewer than half of accounts have `signal_confidence = 'confirmed'`. The Dallas dimension has 387 of 1,479 accounts confirmed (26.2%), so this alerts by design: the score under-represents the other 73.8% of the base, and the alert keeps that limitation visible.

**10. Fit-score range.** Alert if any score falls outside 0–100. The practical maximum is 90 because first-party ordering and delivery-only are mutually exclusive; a value above 90 means the rubric or a source signal changed.

**11. Queue reconciliation.** `mart_sales_queue` must equal non-chain accounts, and `mart_cs_queue` must equal onboarded accounts. The Dallas run has 1,477 sales rows and 53 CS rows, with 13 CS accounts flagged at risk. A mismatch means a filter or join changed.
