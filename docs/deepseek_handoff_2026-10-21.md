# DeepSeek harness handoff: RALI ICP layer

## Objective

Review and exercise the Popmenu-relevant ICP research layer in RALI. Check that public homepage clues, product hypotheses, mock CRM state, and outreach eligibility remain separate. Report or fix only concrete defects. Keep the Chicago pilot and its existing scoring behavior intact.

## Current state

The source of truth is `/Users/tylerroessel/Desktop/rali` on `main`. The ICP implementation began in commit `9873954`. The local virtual environment now matches all checked-in package pins, including dbt Core 1.12.6 and postgres adapter 1.11.0. The earlier dbt 1.9.0 installation caused the `accepted_values` test parse error; the newer pinned version parses successfully without a project SQL change.

On October 21, 2026, a full build against a fresh disposable Postgres instance and the committed 200-account sample passed **197/197 nodes**, including **173 data tests**, with zero warnings, errors, or skips. The research view returned **197 accounts**, **73 rows with homepage evidence fragments**, **4 rows flagged as possible multi-location groups** across two shared domains, and **0 rows ready for outreach**. The mock reverse-ETL script emitted valid sample payloads using `observed_capability`. The test container was stopped and removed afterward. The live warehouse was not rebuilt.

## Source of truth

- Repo: `/Users/tylerroessel/Desktop/rali`; inspect `git status --short --branch` and HEAD before work.
- Scope and first-party Popmenu links: `docs/popmenu_icp.md`.
- Models and tests: `models/marts/mart_sales_queue.sql`, `models/marts/mart_rep_research_queue.sql`, `models/marts/schema.yml`, `tests/assert_rep_research_queue_coverage.sql`.
- Consumers: `scripts/sync_to_crm.py`, `mock_crm_records.json`, inactive `n8n/outbound_harness.json`.
- Other project mirrors and older harness checkouts are reference material, not this repo's source of truth.

## What changed

1. `intent_signal` became `observed_capability` in the sales queue. Values now describe observed fragments or unknown states, rather than implying first-party ownership, marketplace dependence, or buying intent. Suggested actions now begin with research and verification.
2. `mart_rep_research_queue` is an additive view over every sales-queue account. It adds evidence fragments, fetch status and time, observed vendors, a shared-domain location-group clue, a use-case hypothesis, mock CRM review state, and a next research step. `demo_fit_score` is the unchanged legacy score, labeled as a demo rubric. The view does not merge accounts or establish a common buyer.
3. Every row has `outreach_ready = false`. Actual customer, opportunity, owner, duplicate, and suppression status require a check in Popmenu's CRM. The mock CRM cannot answer those questions.
4. The mock reverse-ETL, mock CRM JSON, and inactive n8n outbound template now use `observed_capability`. The drafting prompt warns against turning a clue into intent or proven pain. The n8n template still stops at human Slack approval and does not contact restaurants.
5. New dbt checks cover capability values, view uniqueness, mock CRM review states, a closed outreach gate, and one research row per sales account. README and decision notes explain evidence limits.

No Dallas territory, new market extract, crawler, contact enrichment, actual CRM integration, automatic outreach, or score recalibration was added.

## Allowed actions

Inspect the repo, reproduce tests against a disposable database, and make small fixes only for reproducible failures. Review shared-domain candidates, null or unknown homepage states, view cardinality, and renamed-field consumers. Report documentation inconsistencies with exact file and line. Keep edits narrow.

## Do not touch

Do not change the pilot city, scoring weights, extraction scope, or outbound workflow state. Do not refetch websites, contact restaurants, write to a real CRM, deploy, or push a branch. Do not run a full refresh against a shared warehouse. Do not turn a missing homepage fragment into a claim that a capability is absent, or a mock CRM nonmatch into a verified prospect.

## Known risks

- This Chicago sample is not Popmenu's validated ICP. Public product pages cover additional restaurant formats and location counts.
- A shared domain is a group candidate, not proof of an account hierarchy or common buyer.
- Homepage-only scanning can miss JavaScript-injected or off-homepage flows.
- The research view is not wired into a live send path. The mock sync and inactive n8n template are separate demonstrations.
- Older output files under `docs/` predate the new view. The results here came from the isolated sample build, not the live warehouse.

## Verification

Use the pinned dependencies and an isolated Postgres target. The full sample build used `dbt build` with `--full-refresh` and `--vars '{use_sample_data: true}'`. The command passed all 197 nodes. A database is required even when using sample seeds. Confirm the following query returns `197 | 4 | 0` on the committed sample:

```sql
select count(*) as accounts,
       count(*) filter (where possible_multi_location_group) as group_candidates,
       count(*) filter (where outreach_ready) as outreach_ready
from marts.mart_rep_research_queue;
```

Also verify one research row per sales account, evidence and hypothesis wording, and `observed_capability` in the mock sync and n8n query.

## Stop conditions

Stop and ask Tyler before using a live warehouse, real CRM, outbound messaging, a push, or a product-scope change. If the isolated build passes and no concrete defect appears, report that result without inventing extra work.

## Expected output

Return exact HEAD and git status; tests and queries run with results; reproducible defects and file/line fixes; remaining live-system limits; and a direct judgment on whether the ICP layer is ready to show as a portfolio example. Keep observations, hypotheses, and genuine buying intent distinct.
