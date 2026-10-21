# RALI — Restaurant Account Lifecycle Intelligence

**The real/synthetic boundary is the first thing to understand about this project.** Restaurant identity, address, and website signals are extracted from OpenStreetMap and observed public web pages. Everything about the *account lifecycle* — funnel entry, demos, closes, onboarding, orders, support tickets, renewals, health scores, and every date attached to them — is synthetic, generated with `random.seed(42)` and labelled `source_system = 'synthetic'` in the warehouse. No conversion rate, retention number, or revenue implication in this repository describes a real company or a real market.

> **Build status: all phases 0–6 complete.** The committed test log is [`docs/dbt_test_output.txt`](docs/dbt_test_output.txt); the offline sample path is verified. Measured counts below come from the committed extract and the Supabase warehouse.

RALI models a restaurant-tech go-to-market and customer-success motion from prospect through post-sale lifecycle. It is built as a dbt project on Supabase Postgres, with four warehouse schemas (`raw`, `staging`, `intermediate`, `marts`), identity resolution over messy map data, explainable account scoring, and monitoring checks that are designed to catch the failure modes this kind of pipeline actually has.

The audience is hiring managers at restaurant-tech companies. The project is meant to read as careful systems work: explicit boundaries, inspectable evidence, tested joins, and documented tradeoffs.

## What it demonstrates

- **Extract + load into hosted Postgres** with `COPY ... FROM STDIN`, idempotent re-runs, and schema isolation from Supabase's Data API.
- **Identity resolution** over OSM records: a conservative match ladder (street name, house + street, full address, coordinate fallback, and a 50 m proximity supplement), survivorship by record richness, a visible `source_record_count`, and a committed [50-cluster audit](docs/dedup_audit_stratified.md) with 10/10 merge precision and 40/40 split precision.
- **Evidence-based enrichment**: homepage-only website fingerprints that store the matched fragment strings, not just booleans.
- **Synthetic lifecycle generation** that is deterministic and deliberately messy, with the mess documented rather than hidden.
- **dbt marts** for a sales queue, a customer-success queue, a CRM lifecycle funnel, a raw-event funnel, and per-account health.
- **An n8n approval harness** that drafts one outbound message and blocks it at a human Slack approval step.
- **A reverse-ETL sync simulation** that diffs the warehouse against a mock CRM and emits idempotent create/update payloads.
- **A rules-based fit score** that can be explained in one paragraph without opening the code.
- **Monitoring and tests** that answer "how would I know it broke?" rather than only "does it run?"

## Source scope

The account universe is Chicago full-service restaurants: `amenity=restaurant` inside `41.64,-87.94,42.03,-87.52`, nodes and ways, with a non-empty `name`. `amenity=fast_food` is out of scope. Outlets tagged with `brand` or `brand:wikidata` are excluded before load and counted in the Phase 1 gate report; the curated chain alias seed is a second, normalized-name check rather than the primary filter. This is a scope choice: the interesting sales motion is the independent operator, not the chain's central procurement team.

## Website signals

1,569 accounts have a public website. Deduping to normalized hosts gives 1,429 domains; 4 are third-party platform pages (7 accounts) and are not fetched, leaving 1,425 homepage requests. 1,109 returned HTTP 200 (77.8% of attempts). Of those, 491 show online ordering (44.3%), 376 reservations (33.9%), 231 delivery-marketplace links (20.8%), and 643 a recognized site platform (58.0%). Evidence fragments are stored per domain; 229 successful pages had no known fragment, which is a limitation of raw-HTML matching, not proof of absence.

## Synthetic lifecycle

925 of 2,644 accounts enter the funnel (35.0%): 370 book a demo, 111 close won, 94 onboard, 75 place a first order, and 53 reach 30-day active. The funnel is deliberately messy: 6 won accounts are explicit handoff leaks with no onboarding, 4 of the 53 active accounts get a support ticket, and 4 onboarded-never-ordered accounts get a renewal_due. All 1,636 events are `source_system = 'synthetic'`, use deterministic `uuid5` ids, and reproduce byte-for-byte with `random.seed(42)`.

## Marts

- `dim_account` — 2,644 accounts, fit score 0–90 (the practical max is 90 because ordering and delivery-only are mutually exclusive).
- `mart_sales_queue` — 2,638 independent accounts ranked by fit; 361 priority, 815 nurture, 1,462 low.
- `mart_cs_queue` — 94 onboarded accounts; 23 at risk, 49 expansion reviews, 4 support check-ins, 4 renewal saves.
- `funnel_summary` — 925 → 370 → 111 → 94 → 75 → 53 across the six raw stages.
- `mart_lifecycle_funnel` — CRM stages Lead 925 → SQL 370 → Opportunity 111 → Customer 94 → Active 75, with stage conversion and median days.

Both queues expose `signal_confidence`, `failure_class`, and `signal_coverage_pct` as top-level columns. Queue coverage is 37.2% confirmed; the other 62.8% are flagged as unknown rather than silently treated as “no signal.”

## Outbound approval harness (n8n)

[`n8n/outbound_harness.json`](n8n/outbound_harness.json) is an inactive, importable workflow: Postgres pulls one row from `mart_sales_queue`, an OpenAI node drafts exactly two sentences, a Code guardrail checks length (80–500), sentence count (exactly 2), URLs, and placeholders, and an IF node routes the draft to Slack for a human approval reply. Failed drafts go to a hold branch and never reach Slack. The workflow does not auto-send; approval is a human action. Import it, set the Postgres/OpenAI/Slack credentials, and replace the `#sales-approvals` channel placeholder.

## Operationalizing the Warehouse (Reverse ETL)

The warehouse is not useful if the sales team has to copy numbers into the CRM by hand. [`scripts/sync_to_crm.py`](scripts/sync_to_crm.py) simulates the reverse-ETL edge:

1. **Read the curated state.** Pull `mart_sales_queue` rows with `fit_score >= 80` from Supabase.
2. **Read the current CRM state.** Load the small [`mock_crm_records.json`](mock_crm_records.json) file.
3. **Diff in the edge process.** Match on `account_id`: missing accounts are creates; existing accounts with a different `fit_score` are updates; equal scores are unchanged; CRM-only records are ignored so a sync never deletes.
4. **Emit only the changes.** Print the JSON payloads a CRM API would receive, including `sync_timestamp`, `crm_id` for updates, and a deterministic `idempotency_key` derived from the desired state.

```bash
python scripts/sync_to_crm.py --mock-crm mock_crm_records.json
# demo/reproducible variants:
python scripts/sync_to_crm.py --limit 5
python scripts/sync_to_crm.py --sync-timestamp 2026-10-21T12:00:00Z
```

Current result against the committed mock: **361 priority accounts → 358 creates, 1 update, 2 unchanged, 1 CRM-only ignored, 359 payloads**. The single update is Asadito (70 → 90). Running the same diff twice with a fixed timestamp produces byte-identical payloads and identical idempotency keys.

The architectural point is that the **warehouse owns the business state** — rank, fit score, territory, intent, confidence — while the sync edge owns only the diff and the API call. The CRM receives idempotent upserts, not a re-send of the whole queue. A production version would add OAuth/secrets, a real CRM client, batching, rate-limit handling, retries with a dead-letter path, and an audit log. This is the "connect two systems with no native integration" pattern without pretending the mock is a real integration.

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

Verified on the committed seeds: 200 accounts, 123 events, a 197-row sales queue, a 7-row CS queue, and 140/140 tests with zero warnings. The run is captured in [`docs/sample_build_output.txt`](docs/sample_build_output.txt). A Postgres target is still required (dbt seeds into it), but the live raw tables are not. Use `--full-refresh` when the target already contains live marts so the incremental event fact is replaced rather than merged.

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

- **OSM is not a business registry.** Closures, renames, and duplicate nodes are normal. Dedup precision is audited at 100% on a stratified sample of 50 clusters. Recall is not measured — the under-merge rate for same-name records >50m apart with no shared address is unknown, estimated under 2%. The dedup is deliberately precision-biased: a TAM list should not silently drop accounts.
- **The dedup rate is 0.38%.** 2,654 raw records became 2,644 accounts (10 merges). The stratified 50-cluster audit found 10/10 merge precision and no false splits, but recall is unmeasured. The low rate is plausible for this query (only explicitly tagged restaurants, chains removed) and is a limitation, not proof of completeness.
- **Coverage is incomplete.** OSM maps roughly 50–65% of Chicago's restaurant universe by common estimates. This is a representative sample of the mapped market, not a census; counts describe named, independent, full-service restaurants in the bbox, not every restaurant in Chicago.
- **Territory has an Unknown bucket.** 470 accounts (17.8%) have neither a usable postcode nor a city and are retained as `Unknown` rather than dropped; territory slicing is weaker for them.
- **Homepage-only fingerprinting undercounts.** Ordering widgets are often injected by JavaScript or a third-party script that does not appear in raw HTML. A missing signal is not evidence that the restaurant lacks the capability.
- **Signal coverage is biased.** Signal-based fit components under-represent 37.3% of the website-account base (586 of 1,569) where the homepage could not be fingerprinted; accounts in this population are not known to lack these signals. The earlier 34.7% figure mixed 545 domain rows with a 1,569-account denominator; the account-weighted figure is 37.3% including the 7 skipped third-party accounts.
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
