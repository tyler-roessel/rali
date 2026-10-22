# RALI — Restaurant Account Lifecycle Intelligence

Restaurant GTM teams need a reliable way to identify accounts, prioritize outreach, and see what happens after a sale. RALI turns public Dallas restaurant records and website signals into a deduplicated account model and sales queue, then uses clearly labelled synthetic lifecycle events to exercise onboarding, adoption, renewal, and customer-success reporting. Its matching rules, tests, and failure checks make each output traceable to its inputs.

**The real/synthetic boundary is the first thing to understand about this project.** Restaurant identity, address, and website signals are extracted from OpenStreetMap and observed public web pages. Everything about the *account lifecycle* — funnel entry, demos, closes, onboarding, orders, support tickets, renewals, health scores, and every date attached to them — is synthetic, generated with `random.seed(42)` and labelled `source_system = 'synthetic'` in the warehouse. No conversion rate, retention number, or revenue implication in this repository describes a real company or a real market.

> **Build status: Dallas run complete (2026-10-21).** `dbt build` passed 197/197 nodes with zero warnings or errors. Measured counts below come from the live Dallas extract and the Supabase warehouse. The committed test log [`docs/dbt_test_output.txt`](docs/dbt_test_output.txt) is from the earlier Chicago pilot; the offline sample path remains a Chicago test fixture.

RALI models a restaurant-tech go-to-market and customer-success motion from prospect through post-sale lifecycle. It is built as a dbt project on Supabase Postgres, with four warehouse schemas (`raw`, `staging`, `intermediate`, `marts`), identity resolution over messy map data, explainable account scoring, and monitoring checks that are designed to catch the failure modes this kind of pipeline actually has.

## What it demonstrates

- **Extract + load into hosted Postgres** with `COPY ... FROM STDIN`, idempotent re-runs, and schema isolation from Supabase's Data API.
- **Identity resolution** over OSM records: a conservative match ladder (street name, house + street, full address, coordinate fallback, and a 50 m proximity supplement), survivorship by record richness, and a visible `source_record_count`. The [50-cluster audit](docs/dedup_audit_stratified.md) with 10/10 merge precision and 40/40 split precision was run on the earlier Chicago sample; the Dallas extract uses the same unchanged rules but has not been re-audited.
- **Evidence-based enrichment**: homepage-only website fingerprints that store the matched fragment strings, not just booleans.
- **Synthetic lifecycle generation** that is deterministic and deliberately messy, with the mess documented rather than hidden.
- **dbt marts** for a sales queue, a customer-success queue, a CRM lifecycle funnel, a raw-event funnel, and per-account health.
- **An n8n approval harness** that drafts one outbound message and blocks it at a human Slack approval step.
- **A Sales-to-CX exception queue** with territory routing and an inactive workflow for internal handoff alerts.
- **A reverse-ETL sync simulation** that diffs the warehouse against a mock CRM and emits idempotent create/update payloads.
- **A CRM identity-resolution waterfall** with exact domain, exact phone+address, and fuzzy name+geo matching; sub-95% candidates are flagged for human review.
- **A rules-based fit score** that can be explained in one paragraph without opening the code.
- **A rep research view** that separates homepage clues, product hypotheses, possible shared-domain groups, and CRM checks. [ICP scope and workflow](docs/popmenu_icp.md).
- **Monitoring and tests** that answer "how would I know it broke?" rather than only "does it run?"

## Source scope

The account universe is Dallas full-service restaurants: `amenity=restaurant` inside `32.60,-96.99,33.02,-96.55`, nodes and ways, with a non-empty `name`. The bbox covers Dallas plus its inner-ring suburbs (Richardson, Garland, Irving, Mesquite, Addison, Carrollton, Plano and others), so `territory` is Dallas-centric rather than a Dallas city limit. `amenity=fast_food` is out of scope. The Overpass response returned 1,785 elements; 302 outlets tagged with `brand` or `brand:wikidata` were excluded before load, leaving **1,483 raw records**. The curated chain alias seed is a second, normalized-name check rather than the primary filter. This is a scope choice: the interesting sales motion is the independent operator, not the chain's central procurement team.

## Website signals

694 accounts have a public website. Deduping to normalized hosts gives 624 domains; 1 is a third-party platform page and is not fetched, leaving 623 homepage requests. 473 returned HTTP 200 (75.9% of attempts). Of those, 157 show online ordering (33.2%), 84 reservations (17.8%), 87 delivery-marketplace links (18.4%), and 241 a recognized site platform (51.0%). Evidence fragments are stored per domain; 137 successful pages had no known fragment, which is a limitation of raw-HTML matching, not proof of absence.

## Synthetic lifecycle

518 of 1,479 accounts enter the funnel (35.0%): 207 book a demo, 62 close won, 53 onboard, 42 place a first order, and 29 reach 30-day active. The funnel is deliberately messy: 3 won accounts are explicit handoff leaks with no onboarding, 2 of the 29 active accounts get a support ticket, and 2 onboarded-never-ordered accounts get a renewal_due. All 915 events are `source_system = 'synthetic'`, use deterministic `uuid5` ids, and reproduce byte-for-byte with `random.seed(42)`; the Dallas build recorded zero stage-order violations.

## Marts

- `dim_account` — 1,479 accounts, fit score 0–90 (the practical max is 90 because ordering and delivery-only are mutually exclusive).
- `mart_sales_queue` — 1,477 independent accounts ranked by fit; 134 priority, 383 nurture, 960 low.
- `mart_rep_research_queue` — additive view with evidence, research prompts, possible multi-location groups, and a closed outreach gate. The Dallas build returns 1,477 rows, 125 with a possible shared-domain group, and 0 ready for outreach.
- `mart_cs_queue` — 53 onboarded accounts; 13 at risk, 27 expansion reviews, 2 support check-ins, 2 renewal saves.
- `mart_handoff_exceptions` — 9 closed-won Dallas accounts missing onboarding, with a demo owner assignment and a stable notification key.
- `funnel_summary` — 518 → 207 → 62 → 53 → 42 → 29 across the six raw stages.
- `mart_lifecycle_funnel` — CRM stages Lead 518 → SQL 207 → Opportunity 62 → Customer 53 → Active 42, with stage conversion and median days.
- `crm_identity_map` — 1,479 accounts; 0 matched, because the committed mock CRM and its resolution seed are still the Chicago demo set. No Dallas account is claimed as a CRM match.

Both queues expose `signal_confidence`, `failure_class`, and `signal_coverage_pct` as top-level columns. Dallas queue coverage is 26.2% confirmed; the other 73.8% are flagged as unknown rather than silently treated as “no signal.”

## Outbound approval harness (n8n)

[`n8n/outbound_harness.json`](n8n/outbound_harness.json) is an inactive, importable workflow: Postgres pulls one row from `mart_sales_queue`, an OpenAI node drafts exactly two sentences, a Code guardrail checks length (80–500), sentence count (exactly 2), URLs, and placeholders, and an IF node routes the draft to Slack for a human approval reply. Failed drafts go to a hold branch and never reach Slack. The workflow does not auto-send; approval is a human action. Import it, set the Postgres/OpenAI/Slack credentials, and replace the `#sales-approvals` channel placeholder.

## Sales-to-CX handoff alerts

The CS queue begins after onboarding, so it cannot surface a closed-won account that never reaches that stage. [`mart_handoff_exceptions`](models/marts/mart_handoff_exceptions.sql) lists those accounts and assigns a demo CX owner by territory. The inactive [`n8n/handoff_alerts.json`](n8n/handoff_alerts.json) template can notify that person internally after private recipient mapping is configured. It logs accepted alerts to avoid ordinary duplicate runs; it does not contact restaurants. [Setup and limits](docs/handoff_alerts.md).

## Operationalizing the Warehouse (Reverse ETL)

The warehouse is not useful if the sales team has to copy numbers into the CRM by hand. [`scripts/sync_to_crm.py`](scripts/sync_to_crm.py) simulates the reverse-ETL edge:

1. **Read the curated state.** Pull `mart_sales_queue` rows with `fit_score >= 80` from Supabase.
2. **Read the current CRM state.** Load the small [`mock_crm_records.json`](mock_crm_records.json) file.
3. **Diff in the edge process.** Match on `account_id`: missing accounts are creates; any difference across the fields sent to the CRM triggers an update, including a field absent from the mock record; equal records are unchanged; CRM-only records are ignored so a sync never deletes.
4. **Emit only the changes.** Print the JSON payloads a CRM API would receive, including `sync_timestamp`, `crm_id` for updates, and a deterministic `idempotency_key` derived from the desired state.

```bash
python scripts/sync_to_crm.py --mock-crm mock_crm_records.json
# demo/reproducible variants:
python scripts/sync_to_crm.py --limit 5
python scripts/sync_to_crm.py --sync-timestamp 2026-10-21T12:00:00Z
```

Current Dallas result against the committed mock: **134 priority accounts → 134 creates, 0 updates, 0 unchanged, 4 CRM-only ignored, 134 payloads**. The mock records are the Chicago demo set, so they do not match any Dallas `account_id`; that is a fixture limitation, not a Dallas CRM result. Running the same diff twice with a fixed timestamp produces byte-identical payloads and identical idempotency keys.

The architectural point is that the **warehouse owns the business state** — rank, fit score, territory, intent, confidence — while the sync edge owns only the diff and the API call. The CRM receives idempotent upserts, not a re-send of the whole queue. A production version would add OAuth/secrets, a real CRM client, batching, rate-limit handling, retries with a dead-letter path, and an audit log. This is the "connect two systems with no native integration" pattern without pretending the mock is a real integration.

## CRM Identity Resolution

[`scripts/resolve_identities.py`](scripts/resolve_identities.py) compares `dim_account` to [`seeds/mock_crm_accounts.csv`](seeds/mock_crm_accounts.csv) and writes [`seeds/crm_identity_resolution.csv`](seeds/crm_identity_resolution.csv). [`models/marts/crm_identity_map.sql`](models/marts/crm_identity_map.sql) joins that output back to the dimension and CRM records for a reviewable map.

Matching waterfall:

1. **Exact domain** — 100% confidence.
2. **Exact phone + normalized address** — 100% confidence.
3. **Fuzzy name + geo** — `100 × (0.70 × name_similarity + 0.30 × geo_score)`, with a 500 m radius and a 0.55 name-similarity floor.

Any candidate below **95%** is written with `needs_human_review = true`. Unmatched accounts have `match_method = 'unmatched'`, a null `crm_account_id`, and confidence 0; they are not review cases because there is no candidate to review.

Current Dallas result: **1,479 accounts → 0 matched**, all **1,479 unmatched**, zero review candidates, and the 4 Chicago mock records are ignored as CRM-only. The mock CRM and `seeds/crm_identity_resolution.csv` were not regenerated for Dallas, so this section demonstrates the matching mechanics rather than a Dallas CRM state. Unmatched rows are retained in the map rather than dropped; the model exposes `is_matched`.

Regenerate and build:

```bash
python scripts/resolve_identities.py
dbt seed --profiles-dir . --select mock_crm_accounts crm_identity_resolution
dbt build --profiles-dir . --select crm_identity_map
```

The committed resolution seed makes the model buildable from a clean clone; the script is the reproducible generator, not a live API integration.

## Architecture


```
Overpass API ──► raw.osm_restaurants
                        │
                        ▼
              staging.stg_restaurants
                        │
                        ▼
        intermediate.int_account_deduped ◄── seeds.chain_name_lookup
                        │
       homepage fetch ──┴──► raw.website_signals
                        │
                        ▼
                 marts.dim_account ──────────────► marts.mart_sales_queue
                        │
synthetic generator ──► raw.lifecycle_events
                        │
                        ▼
              marts.fct_lifecycle_event
                        │
                        ├──► marts.fct_account_health ──► marts.mart_cs_queue
                        └──► marts.funnel_summary
```

The dbt DAG is intentionally shallow. Staging normalizes and types; the intermediate model owns the hard identity decision; marts are business-facing and do not re-derive identity.

## Schemas

| Schema | Written by | Contents |
|---|---|---|
| `raw` | Python extract/load scripts | `osm_restaurants`, `website_signals`, `lifecycle_events` |
| `staging` | dbt views + seeds | normalized restaurant records, chain aliases |
| `intermediate` | dbt view | deduplicated accounts with survivorship metadata |
| `marts` | dbt tables/incremental | dimensions, facts, sales/CS queues, funnel summary |

Nothing is created in `public`. Supabase exposes `public` through its Data API; keeping warehouse objects in named schemas means the data is not reachable with the `anon` key by default, without relying on RLS configuration for tables that were never meant to be an API.

## Quickstart

### 1. Supabase project

Create a free Supabase project. In **Project Settings → Database → Connection string**, choose **Session pooler** (port `5432`), not the direct connection and not the transaction pooler.

- New projects are often IPv6-only on the direct `db.<ref>.supabase.co` host. The session pooler is reachable over IPv4.
- The session-pooler username is `postgres.<project-ref>`, not `postgres`.
- Port `6543` (transaction pooler) is not supported by this project: it breaks prepared statements and DDL.

### 2. Local environment

```bash
git clone <your-fork-url> rali
cd rali
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with SUPABASE_HOST / SUPABASE_USER / SUPABASE_DB_PASSWORD
dotenv run -- dbt deps --profiles-dir .
dotenv run -- dbt debug --profiles-dir .
```

`profiles.yml` lives in the repo and contains no secrets; it reads the three values from `.env` via `env_var()`. dbt does not read `.env` by itself, so the commands are wrapped in `dotenv run --`, which loads the file and executes dbt with those variables in the process environment. (Python extract scripts load `.env` themselves via `python-dotenv`.)

### 3. Build

```bash
python -m extract.pull_osm
python -m extract.fingerprint_websites
python -m extract.generate_lifecycle
dotenv run -- dbt build --profiles-dir .
```

`dbt build` runs seeds, models, and tests in DAG order. The committed test log is in [`docs/dbt_test_output.txt`](docs/dbt_test_output.txt).

### 4. Rebuild without a live warehouse

The repository commits a 200-account sample (210 raw rows, 119 website-signal rows, 123 lifecycle events). `use_sample_data: true` switches the three raw source identifiers to the sample seed tables, so the same staging, dedup, scoring, and mart SQL runs without Overpass or website requests:

```bash
dotenv run -- dbt seed --profiles-dir . --full-refresh
dotenv run -- dbt build --profiles-dir . --full-refresh --vars '{use_sample_data: true}'
```

The earlier recorded build verified 200 accounts, 123 events, a 197-row sales queue, a 7-row CS queue, a 200-row identity map, and 167/167 tests with zero warnings; its log is [`docs/sample_build_output.txt`](docs/sample_build_output.txt). On October 21, 2026, the full sample build was rerun in an isolated local Postgres database with the pinned dbt 1.12.6 environment: **197/197 nodes passed, including 173 data tests**, with zero warnings or errors. The new research view returned 197 accounts, four rows with a possible shared-domain group, and zero rows ready for outreach. [Verification and DeepSeek handoff](docs/deepseek_handoff_2026-10-21.md). A Postgres target is still required (dbt seeds into it), but live raw tables are not. Run `--full-refresh` only against an isolated test target because it replaces the incremental event fact and other existing target relations. The committed sample seeds remain a 200-account Chicago fixture used to test SQL without network access; they are not the Dallas warehouse.

## Monitoring

[`monitoring/checks.sql`](monitoring/checks.sql) contains runnable checks for:

- row-count spikes/drops versus the previous run,
- null-rate drift on `territory` and `full_address`,
- website-signal freshness (7 days),
- duplicate/over-merge drift on `dedup_key`,
- orphaned lifecycle events,
- signal coverage, fit-score range, and queue reconciliation (sales = independent accounts; CS = onboarded accounts).

[`docs/how_id_know_it_broke.md`](docs/how_id_know_it_broke.md) explains the threshold behind each check and the failure it catches. An optional `pg_cron` schedule is included as a comment; free-tier projects can run the file manually.

## Real vs synthetic, in one table

| Data | Source | Status |
|---|---|---|
| Restaurant name, address, cuisine, phone, website, lat/lon | OpenStreetMap via Overpass | Real, public, ODbL |
| Chain/brand classification | Curated seed + normalized-name match | Derived |
| Online ordering / reservations / delivery / platform signals | Homepage HTML of the restaurant's public website | Observed, with stored evidence |
| Account IDs | `uuid5(dedup_key)` | Deterministic |
| Funnel events, timestamps, support tickets, renewals | Generated in `extract/generate_lifecycle.py` | **Synthetic** |
| Fit score, adoption score, risk flags | Rules over the above | Derived; not a prediction |

No owner names, personal emails, or mobile numbers are collected. Business phone and website are taken from public map data. No Google Places, Yelp, or Foursquare content is stored or committed.

## Limitations

- **OSM is not a business registry.** Closures, renames, and duplicate nodes are normal. On the earlier Chicago sample, dedup precision was audited at 100% on a stratified 50-cluster sample; the Dallas run uses identical rules but was not re-audited. Recall is not measured — the under-merge rate for same-name records >50m apart with no shared address is unknown. The dedup is deliberately precision-biased: a TAM list should not silently drop accounts.
- **The Dallas dedup rate is 0.27%.** 1,483 raw records became 1,479 accounts (4 merges). Recall is unmeasured and this run has not been stratified-audited. The low rate is plausible for this query (only explicitly tagged restaurants, chains removed) and is a limitation, not proof of completeness.
- **Coverage is incomplete.** OSM does not map every restaurant. This is a representative sample of the mapped Dallas market, not a census; counts describe named, independent, full-service restaurants in the bbox, not every restaurant in Dallas.
- **Territory has a large Unknown bucket.** 665 accounts (45.0%) have neither a usable postcode nor a city and are retained as `Unknown` rather than dropped; Dallas OSM address coverage is sparser than the earlier Chicago extract, so territory slicing is materially weaker here.
- **Homepage-only fingerprinting undercounts.** Ordering widgets are often injected by JavaScript or a third-party script that does not appear in raw HTML. A missing signal is not evidence that the restaurant lacks the capability.
- **Signal coverage is biased.** Only 26.2% of accounts (387 of 1,479) have a confirmed homepage signal. 785 accounts (53.1%) record no website at all, and 116 of 623 fetchable domains returned HTTP errors, so signal-based fit components under-represent this population; these accounts are not known to lack the capabilities.
- **403 is not 404.** A 403 is a live site blocking the crawler; a 404 is a dead URL. Both are `unknown_unreachable`, but they are not the same operational fact.
- **The lifecycle is synthetic.** It is calibrated to be plausible, not to reproduce any company's funnel. Funnel outputs are a demonstration of modeling, not a benchmark.
- **A free Supabase project can pause.** The committed sample path lets a reviewer rebuild the warehouse without the live raw tables; it still needs a Postgres target.
- **Production would need more than this repo has**: retries with backoff and a dead-letter path for extraction, schema-drift handling for source tags, RLS if any table were ever exposed, PII review, secrets rotation, and a scheduler with alert routing. The current monitoring checks are a floor, not a production SLO.
- **No ML.** The fit score is a weighted rubric. It is meant to be argued with in a meeting, not trusted as a prediction.

## Attribution

Restaurant data © OpenStreetMap contributors, available under the [Open Database License](https://www.openstreetmap.org/copyright). Website signals are derived from publicly accessible pages; only small evidence fragments are stored, not page content.

## Repository layout

```
rali/
├── extract/            # Overpass pull, website fingerprints, synthetic lifecycle
├── seeds/              # chain/cuisine/lifecycle lookups + 200-account offline sample
├── n8n/                # outbound approval harness (inactive template)
├── scripts/            # reverse ETL CRM sync simulation
├── mock_crm_records.json
├── models/
│   ├── staging/        # typed, normalized views
│   ├── intermediate/   # identity resolution
│   └── marts/          # dim/fct/queues
├── macros/             # schema naming + reusable normalization
├── tests/generic/      # custom data tests
├── monitoring/         # SQL checks and pg_cron note
└── docs/               # decisions, failure model, committed test log
```
