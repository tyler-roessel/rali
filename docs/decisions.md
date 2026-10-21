# Decisions

This file records the project's design choices and their tradeoffs so the decisions can be understood without the code open.

## 1. Why Supabase Postgres, and why this connection topology

The project could run on a local DuckDB file. It runs on Supabase instead to exercise hosted-Postgres operations (schemas, roles, connection pooling, DDL). Those operational choices matter when data models need to feed sales and customer-success workflows beyond a single-user file.

The connection uses the **session pooler on port 5432**:

- New Supabase projects are frequently IPv6-only on the direct `db.<ref>.supabase.co` host. That fails on many home and office networks.
- The session pooler is IPv4-reachable and keeps a session for the life of the connection, so prepared statements and DDL work.
- The transaction pooler on `6543` is explicitly out of scope. It multiplexes transactions across sessions, which breaks the prepared statements and DDL that dbt issues. A pipeline that "works" on 6543 until the first `CREATE TABLE` is a trap, not a configuration choice.
- The session-pooler username is `postgres.<project-ref>`. Plain `postgres` authenticates against the wrong tenant and fails with a confusing password error.

## 2. Schema isolation

Warehouse objects live in `raw`, `staging`, `intermediate`, and `marts`. Nothing is created in `public`. Supabase exposes `public` through the Data API to the `anon` role; named schemas are not exposed by default. This keeps the warehouse off the API surface without writing RLS policies for tables that were never intended to be an API.

`generate_schema_name` returns the custom schema exactly, rather than dbt's default `<target_schema>_<custom_schema>`. That keeps the physical names predictable for monitoring SQL and for a reviewer browsing the Supabase table editor.

## 3. The real/synthetic boundary

| Layer | Status | Why |
|---|---|---|
| Restaurant identity, address, cuisine, phone, website, coordinates | Real, from OpenStreetMap | Public, ODbL-licensed, reproducible from the Overpass query |
| Chain classification | Derived from a curated alias seed | The alias list is a judgment call and is versioned in the repo |
| Website capability signals | Observed from the homepage | Evidence fragments are stored so a reviewer can spot-check |
| Account IDs | Deterministic `uuid5` of the dedup key | Stable across rebuilds |
| Lifecycle events, timestamps, support tickets, renewals | **Synthetic** | No real CRM data exists for these restaurants; generating it is the only honest option |
| Fit, adoption, risk scores | Rules over the above | Explainable, not predictive |

Every synthetic row carries `source_system = 'synthetic'`. dbt model descriptions and column comments repeat the boundary at the point of use. The README states it in the first 100 words. A reviewer should never be able to cite a funnel number as real.

**Coverage caveat.** OSM coverage of Chicago restaurants is roughly 50–65% of the true universe. RALI is a representative sample of the mapped market, not a census. Counts in this warehouse mean "named, independent, full-service restaurants mapped in this bbox," not "all restaurants in Chicago." This is a limitation to state plainly, not a gap to fill with invented records.

## 4. Identity resolution

The expensive mistake in this dataset is over-merging: collapsing two restaurants with the same name into one account. The rule is therefore conservative, but the handoff's simple `name + full address` key was too strict in practice because OSM addresses are frequently partial. A first pass produced 2,654 records → 2,652 accounts: it missed node/way twins where one record lacked a city, postcode, or house number. The implemented ladder keeps the over-merge guard while recovering those clear duplicates.

1. **Normalize the name**: lowercase, remove apostrophes, turn `&` into `and`, strip punctuation, remove legal/taxonomy tokens (`restaurant`, `the`, `llc`, `inc`, `cafe`), collapse whitespace. Apostrophes are deleted rather than spaced, so `McDonald's` and `McDonalds` match.
2. **Normalize the address**: lowercase, strip unit/suite designators, standardize `street → st`, `avenue → ave`, `boulevard → blvd`, `road → rd`, plus `drive/lane/court/place` and directional prefixes. House-number ranges (`3661-3663`, `3661 3663`) and unit suffixes collapse to the first numeric token for matching; the raw value is preserved for display.
3. **Match ladder**, evaluated in this order:
   - **`street_name`**: same normalized name + same street name, at most one distinct house number across the group, and no conflicting city/postcode. This catches a missing or partial house number without merging two different addresses on the same street.
   - **`street_address`**: same name + same house number + street, with no conflicting city/postcode.
   - **`full_address`**: same name + full normalized address including city/postcode. Used when city/postcode conflict.
   - **`geo_4dp`**: name + coordinates rounded to four decimals (~11 m) when no address is available.
   - **`geo_50m`**: a proximity supplement for name-identical records within ~50 m that the address rules left apart (for example, a corner building with two street names, or one record with no address). It supplements the ladder; it does not replace it.
   - **`uid_fallback`**: name + OSM uid when no address or coordinates exist.
4. **Never match on name alone.** Every rule includes an address, a coordinate, or the unique OSM id. A missing address and missing coordinates produce a key that includes `osm_type:osm_id`, so the record stays separate rather than joining every nameless-address namesake.
5. **Survivorship**: `ROW_NUMBER() OVER (PARTITION BY dedup_key ORDER BY (website IS NOT NULL) DESC, (phone IS NOT NULL) DESC, osm_id, osm_type, osm_uid)` keeps the richest record, not the first one encountered. `source_record_count` is emitted per cluster so an over-merge is visible in the data, not only in a hand-check.

The 50-cluster audit is in [`docs/dedup_audit.md`](dedup_audit.md), with row-level data in [`docs/dedup_audit.csv`](dedup_audit.csv). Result: **50/50 correct (100%)** — 10/10 merge precision, 40/40 split precision. The sample is stratified rather than random: all 10 multi-record clusters, all 8 same-street/different-house clusters, 15 same-name multi-location clusters, and 17 deterministic random singletons. The Wilson 95% lower bound is about 93%, so “100%” means “no errors in 50,” not “provably perfect.” The residual failure mode is under-merging for same-name records more than 50 m apart with no shared address; that is an intentional precision tradeoff. There are no observed over-merges.

**Canonical key vs survivor address.** `int_account_clusters` first assigns every record an `address_key` from the address ladder. The `geo_50m` pass then finds name-identical pairs within ~50 m and assigns both records the lexicographically least `address_key` in the pair as the canonical `dedup_key`. The survivor is chosen independently by richness (website, then phone, then lowest OSM id). That is why The Corner Farmacy's cluster key is the `n bell ave` key while the surviving row is the `n leavitt st` record: the key is a stable cluster identifier, not a claim about the survivor's address. `int_account_deduped` exposes both `dedup_key` (canonical) and `address_key` (the survivor's own pre-pass key), and `match_rule = geo_50m` records which mechanism fired.

**Dedup rate and limitation.** 2,654 raw records became **2,644 accounts**: 10 merges, or **0.38%**. `select count(*), count(distinct dedup_key) from int_account_deduped` returns **2,644 / 2,644**, so the account count is distinct keys, not a row count. `source_record_count` is 1 for 2,634 accounts and 2 for 10; there are **zero** 3+ clusters. This is lower than the 2–5% duplicate rate typical of POI data, and it is a real limitation, not a result to celebrate.

The 50-cluster audit in [`docs/dedup_audit_stratified.md`](dedup_audit_stratified.md) includes all 10 merges plus 10 random full-population singletons, 15 null-website accounts, and 15 null-postcode accounts. Result: **50/50 correct; merge precision 10/10; split precision 40/40.** No over-merges and no false splits were observed. The low rate is plausible because the query only returns elements explicitly tagged `amenity=restaurant` (a building way without the tag is not a duplicate in this extract), chain-tagged records were removed, and Chicago OSM is mature. It may still be over-conservative for old/new addresses and name variants: Luella's Southern Kitchen appears at 4114 N Kedzie and 4609 N Lincoln with the same phone/website; Bongiorno's Cucina and Bongiorno's Deli share an address and phone but have different service names; Friends Sushi, Wow Bao, and Silk Road each have a no-address record 270–400 m from an addressed twin. These are kept separate because the evidence cannot distinguish a move or a second concept from a second location. Recall is unmeasured; the audit is powered to catch over-merging, not to prove completeness.



## 5. Chain and fast-food filtering

This is a two-stage decision, because the stages answer different questions.

**Stage 1 — extract-level exclusion.** The Overpass query uses `amenity=restaurant` only. `amenity=fast_food` is out of scope: the target is independent full-service operators, not quick-service. Records carrying `brand` or `brand:wikidata` are dropped in Python and counted. This is the primary chain filter: a tagged brand is a strong, inspectable signal, and it keeps chain outlets out of the account universe rather than scoring them and discarding them later.

**Stage 2 — normalized-name audit.** `seeds/chain_name_lookup.csv` (64 brands, 116 aliases) is matched by **exact normalized alias equality**, not substring or prefix. It exists to catch residual chain outlets that lack a brand tag — for example, a franchise record named "Dunkin Donuts of Elmhurst". Exact matching is deliberately precision-first: a token-boundary regex on `dunkin` would match the Elmhurst franchise, while exact matching on the curated alias `dunkin donuts` does not; the variant can be added to the alias list with a visible diff. The cost is recall: unrecognized franchise variants stay `is_chain = false` and inflate the independent share. `is_chain` and `chain_brand` are stored on the account, and the Phase 2 gate reports the residual chain share as a floor, not a census.

The Stage 1 chain-exclusion count is reported alongside the final extract count. The Phase 2 gate reports three numbers explicitly: (a) Stage 1 brand-tag exclusions, (b) Stage 2 normalized-name exclusions, and (c) the final independent count. If (b) is under roughly 50, that is a signal that the alias seed is under-matching and needs review, not a number to explain away.

A pre-flight exact-name check on the 2,654 loaded records found 6 residual matches (Protein Bar 5, Roti 1). The low number is not evidence of a broken seed: zero Subway, Starbucks, McDonald's, Chipotle, Dunkin', or other major-chain names remain, because the brand filter already removed them. The Phase 2 dbt model is the authoritative number; if it differs materially from 6, the normalization or alias join is the first place to look.

## 5a. Website fingerprinting (Phase 3)

The account universe has 1,569 accounts with a non-null website. Deduping by normalized host gives **1,429 unique hosts**, which is 140 duplicate account-host mappings overall. Four of those hosts are third-party platform pages (Yelp, Facebook, Instagram, OpenTable) covering 7 accounts, leaving **1,425 first-party hosts** covering **1,562 first-party accounts**: 137 of those accounts share a host with another account. The earlier “140 accounts share a host” shorthand was the all-in duplicate mapping count, not the first-party count. That is under the 2,000 cap.

Rules: one homepage request per domain (`scheme://domain/`), 10 s timeout, at most 3 redirects, 2 s between requests, no crawling. Multiple accounts on one domain produce one fetch and an `account_count`.

Third-party platform pages are **not fetched**. Fetching Yelp or OpenTable would pull data from sources whose terms restrict caching, and a Facebook/Instagram page is not the restaurant's own homepage. Those rows are still written with `fetch_status = 'skipped_third_party'` and a null `evidence`, with the reason in `error_detail`, so the gap is visible and does not look like a failed request.

Signals are matched as lowercase fragments in the raw HTML, the final URL, and the page title:

| Field | Fragments |
|---|---|
| online ordering | `toasttab.com`, `bentobox`, `square.site`, `olo.com`, `chownow`, `order.online`, `slicelife` |
| reservations | `resy.com`, `opentable.com`, `exploretock.com`, `sevenrooms`, `yelp.com/reservations` |
| delivery marketplaces | `doordash`, `ubereats`, `grubhub`, `postmates`, `caviar` |
| site platform | `wix`, `squarespace`, `wordpress`, `shopify`, `webflow`, `godaddy` |

`evidence` stores the matched fragment strings with labels (`ordering:toasttab.com; delivery:doordash; platform:wordpress`), not page content. `online_ordering_vendor` and `reservation_vendor` are the first matching vendor; `site_platform` is the first matching platform in the order above, while evidence retains every match.

Limitations are real: raw HTML misses JavaScript-injected ordering widgets, so a missing signal is not evidence of absence; Cloudflare/403 pages depress the success rate; and bare platform fragments can match footer scripts. The Phase 3 gate reports the success rate and vendor distribution rather than claiming the signal is complete.

**Result.** 1,429 domain rows covering 1,569 accounts; 1,109 fetched `ok` (77.8% of 1,425 attempted, 77.6% of all 1,429). Failures: 230 `http_error`, 61 `dns_error`, 25 `timeout`, 4 `skipped_third_party`. The HTTP errors are dominated by 403 (124), then 404 (28), 429 (15), 401 (4), and four 5xx responses; the remaining 55 are connection/redirect failures with no HTTP status. Of the 1,109 `ok` pages, 880 (79.4%) contained at least one matched fragment; 229 loaded successfully with no known fragment.

| Signal | Domains | Share of ok pages | Accounts covered |
|---|---:|---:|---:|
| Online ordering | 491 | 44.3% | 561 |
| Reservations | 376 | 33.9% | 404 |
| Any delivery marketplace | 231 | 20.8% | 260 |
| Recognized site platform | 643 | 58.0% | 718 |

**Delivery arithmetic.** 231 is the number of unique domains with at least one delivery-marketplace fragment. 359 is the total number of vendor mentions across those domains (159 + 94 + 74 + 25 + 7). A domain can link DoorDash and Grubhub, so the vendor mention count is expected to exceed the domain count.

Ordering vendors: Toast 316, order.online 56, ChowNow 39, Square 34, BentoBox 33, Slice 10, Olo 3. Reservation vendors: OpenTable 196, Resy 111, Tock 39, SevenRooms 27, Yelp reservations 3. Delivery occurrences: DoorDash 159, Grubhub 94, Uber Eats 74, Caviar 25, Postmates 7. Platforms: WordPress 242, Squarespace 180, Wix 161, Webflow 26, GoDaddy 25, Shopify 9. These are observed page fragments, not verified product subscriptions; a footer link is evidence of a relationship, not proof of current usage.

**Signal confidence (before Phase 5).** A page-level `signal_confidence` distinguishes what the homepage check actually established:

| Value | Meaning | Domains | Accounts |
|---|---|---:|---:|
| `confirmed` | HTTP 200 and at least one matched fragment | 880 | 983 |
| `unknown_no_match` | HTTP 200, no known fragment | 229 | 248 |
| `unknown_unreachable` | fetch failed, timed out, DNS failed, or third-party page skipped | 320 | 338 |

That is **586 of 1,569 accounts (37.3%) without a fingerprint**. The often-quoted 545/34.7% mixed 545 domain rows (316 failed + 229 no-match) with a 1,569-account denominator. The correct domain-level figure is 545/1,429 = 38.1%; the account-weighted figure is 579/1,569 = 36.9% excluding the 4 skipped third-party hosts, or 586/1,569 = 37.3% including the 7 accounts behind them. `confirmed` is page-level: it means something matched, not that every absent capability is proven absent.

**403 is not 404.** `failure_class` separates operational failures: `blocked` (401/403/429; 143 domains, 155 accounts), `not_found` (404/410; 28 domains, 28 accounts), `server_error` (5xx; 4 domains), `timeout` (25 domains, 27 accounts), `dns_error` (61 domains, 62 accounts), `connection_or_redirect` (55 domains, 55 accounts), and `skipped_third_party` (4 domains, 7 accounts). A 403 is a live site refusing the crawler; a 404 is a dead URL. Both are `unknown_unreachable`, but they are not the same operational fact.

The Phase 5 fit score awards points only for positive signals. `dim_account` carries `signal_confidence` and `failure_class` so a reviewer can separate “observed absent” from “not observed”; unknown accounts get zero signal points rather than a negative inference. Even a `confirmed` page is raw-HTML evidence, so JavaScript-injected ordering remains a known blind spot.

## 5b. Synthetic lifecycle (Phase 4)

The account identity is real; the lifecycle is completely synthetic. `generate_lifecycle.py` uses `random.Random(42)`, `uuid5` account/event ids, a fixed UTC anchor, and sorted populations before every sample. No `now()` enters the events.

**Selection and conversion.** 925 of 2,644 accounts enter the funnel (35.0%). The stage samples are nested, and the realized rates differ slightly from the targets only because an integer number of accounts cannot hit 84.7% exactly:

| Stage | Count | Target | Realized |
|---|---:|---:|---:|
| Account → prospect | 925 | 35.0% | 35.0% |
| Prospect → demo | 370 | 40.0% | 40.0% |
| Demo → closed won | 111 | 30.0% | 30.0% |
| Won → onboarded | 94 | 85.0% | 84.7% |
| Onboarded → first order | 75 | 80.0% | 79.8% |
| First order → 30-day active | 53 | 70.0% | 70.7% |

Event totals: prospect 925, demo 370, closed won 111, onboarded 94, first order 75, 30-day active 53, support ticket 4, renewal due 4 — **1,636 events across 925 accounts**.

**Messiness.** Six of the 111 won accounts (5.4%) are explicit `handoff_leak` cases: they have a closed_won event with `event_properties = {"handoff_leak": true}` and no onboarded event. The other 11 non-onboarded accounts come from the 85% conversion, not from the leak label. Four of the 53 30-day accounts (7.5%) get a support ticket. Four of the 94 onboarded accounts (4.3%) get a renewal_due without a first_order; the base is onboarded, where a renewal is meaningful, not the whole prospect pool. All four are in the onboarded-never-ordered population.

**Time and order.** Events run from 2025-04-01 to 2026-08-09 (494 days) inside the 18-month design window. Per account, prospect → demo → won → onboarded → first order → 30-day is monotonic; support tickets follow 30-day; renewal follows onboarded. The SQL checks return zero for onboarded-before-closed, first-order-before-onboarded, support-before-30-day, and renewal-before-onboarded. `tests/assert_lifecycle_stage_order.sql` enforces the same rule in dbt.

**Reproducibility.** Two consecutive runs produced identical row counts (1,636), identical event counts, and the same SHA-256 of the sorted `(event_id, account_id, event_name, timestamp)` tuples: `bd7f47cbd38a68f58eb05856e4868736f29c8054ea84fd4554192541bf8962e9`. The hash is printed in the run summary.

## 6. Fit score (rules, not a model)

The score is a 0–100 rubric. Each component is a column-level fact that a reviewer can trace.

| Component | Points | Rationale |
|---|---:|---|
| Independent (not a chain) | +25 | The sales motion targets operator-led accounts; chains have central procurement |
| Has a website | +15 | A working web presence is a precondition for the digital-ordering conversation |
| Has an online-ordering fragment | +15 | A detected ordering path warrants a manual stack review; the fragment does not prove ownership or buying intent |
| Has reservations | +10 | Reservation demand signals a full-service operation with covers to protect |
| Cuisine in the high-fit set | +15 | Full-service cuisines where direct ordering and reservations matter more than at a counter |
| Has a business phone | +10 | A reachable operator is a qualifying signal, not a rich one |
| Delivery fragment without an ordering match | +10 | A direct-ordering discovery question; a missed homepage fragment does not prove absence |
| **Theoretical maximum** | **100** | Practical maximum is 90; ordering and delivery-only are mutually exclusive |

The legacy `delivery_marketplace_only` flag is `has_delivery and not has_online_ordering`: at least one DoorDash/Uber Eats/Grubhub/Postmates/Caviar fragment and no ordering fragment found on the homepage. Its name is stronger than the evidence; it is a scan category, not proof of exclusive marketplace dependence. It is mutually exclusive with the ordering component. That means the practical maximum is **90**, not 100 (25 + 15 + 15 + 10 + 15 + 10 + 0). The `least(100, ...)` cap remains in the SQL, but no account can reach 100. The rubric avoids double-counting these two fragment categories. A reviewer who expects a 100-point scale should read 90 as the top of the achievable range.

The high-fit cuisine set is a seed in [`seeds/cuisine_fit_lookup.csv`](../seeds/cuisine_fit_lookup.csv): full-service and direct-ordering cuisines are `true`; counter/retail categories such as fast food, dessert, bakery, juice, and food court are `false`. It is a hypothesis about where the product fits, not a finding. Tiers: 80–100 priority, 60–79 nurture, below 60 low.

In one paragraph: an account scores 25 for being independent, 15 for having a website, 15 for first-party online ordering, 10 for reservations, 15 for a high-fit cuisine, 10 for a business phone, and 10 for delivery-marketplace dependence without first-party ordering. The maximum attainable is 90 because the last two ordering signals are mutually exclusive. It is a prioritization rubric, not a propensity model.

`dim_account` carries `signal_confidence` and `failure_class`; both queues expose those plus `signal_coverage_pct`, which is the share of rows in that queue with `signal_confidence = 'confirmed'`, repeated per row so a reviewer sorting by `fit_score` sees the evidence state inline. Unknown signal states earn zero signal points but are flagged, not treated as confirmed absences.

The score is not a propensity model and is not trained on outcomes. It is a prioritization device that a sales lead can argue with.

## 6a. Marts and queues (Phase 5)

`dim_account` has 2,644 rows. Fit-score bands: **361 priority** (80–90), **815 nurture** (60–79), **1,468 low** (<60). The practical maximum is 90, not 100, because first-party ordering and delivery-marketplace-only cannot both be true.

`mart_sales_queue` has **2,638 independent accounts** (chains excluded). In the recorded build, the observed-capability categories were: 1,072 website not recorded, 784 website recorded with capability unknown, 561 ordering fragments, 121 delivery fragments without an ordering match, and 100 reservation fragments. Signal coverage was **37.2% confirmed** (982 of 2,638). These category names have since been clarified in SQL; counts need a fresh build to reconfirm. The queue is ranked by fit_score; 361 accounts are in the priority band. The top of the queue is not a shortlist — it is a complete ranked market, intended to be filtered by band, territory, or confidence.

`mart_cs_queue` has **94 rows**, one per onboarded account. **23 are flagged at risk**: 4 support-medium accounts, 4 renewal-high accounts (all onboarded-never-ordered), and 15 additional low-adoption onboarding-recovery accounts. The 4 renewal-high accounts are a subset of the 19 onboarded-never-ordered accounts, so the union is 23. There are also 49 expansion-review accounts, 22 quarterly-business-review accounts, 4 support check-ins, and 4 renewal-save plays. The queue's signal coverage is **37.2% confirmed** (35 of 94). The small queue is expected: 94 of 2,644 accounts onboarded, which is 3.6% of the account base.

`funnel_summary` returns six rows: 925 prospects, 370 demos, 111 won, 94 onboarded, 75 first orders, 53 30-day active; median days between stages are 9.1, 18.3, 8.1, 3.3, and 30.0.

`mart_lifecycle_funnel` maps the raw event names to standard CRM stages through [`seeds/lifecycle_mapping.csv`](../seeds/lifecycle_mapping.csv):

| CRM stage | Raw event | Accounts |
|---|---|---:|
| Lead | `prospect_created` | 925 |
| SQL | `demo_booked` | 370 |
| Opportunity | `closed_won` | 111 |
| Customer | `onboarded` | 94 |
| Active | `first_order` | 75 |

`closed_won` is the proxy for Opportunity because the generator has no separate `opportunity_created` event. `30_day_active`, `support_ticket`, and `renewal_due` are mapped to Active but flagged `counts_toward_funnel = false`; they are post-sale milestones, not new stage arrivals. That is why Active is 75, not 53. Stage conversions are 40.0%, 30.0%, 84.7%, and 79.8%, with median days 9.1, 18.3, 8.1, and 3.3.

`signal_coverage_pct` is the share of rows in the queue with `signal_confidence = 'confirmed'`, repeated per row. It is a queue-level context metric, not an account-level probability.

**Territory limitation.** 470 accounts (17.8%) have neither a usable postcode nor a city and land in `Unknown`; they are retained, but territory slicing is weaker for that group. The `territory` column is never null, so a null-rate check alone would miss this. Phase 6 adds an Unknown-share monitor.

## 6b. Outbound approval harness (n8n)

[`n8n/outbound_harness.json`](../n8n/outbound_harness.json) is an inactive, importable workflow, not a running service. It pulls one row from `mart_sales_queue` with a Postgres node, asks an OpenAI node for exactly two sentences, normalizes the response, then runs a Code-node guardrail: length 80–500, exactly two sentence terminators, no URL, no `[placeholder]` or `{{template}}`. An IF node routes passing drafts to Slack for a human approval reply; failures go to a hold branch and never reach Slack. The workflow does not auto-send. Credentials and the Slack channel are placeholders because the harness must not embed secrets.

## 6c. Reverse ETL (CRM sync simulation)

[`scripts/sync_to_crm.py`](../scripts/sync_to_crm.py) is a local simulation, not a live CRM integration. It reads `marts.mart_sales_queue` where `fit_score >= 80`, matches `mock_crm_records.json` on `account_id`, and emits creates or updates when any desired field differs or is missing from the mock record. Unchanged accounts emit nothing; CRM-only records are ignored so the sync never deletes.

The idempotency key is a SHA-256 of `account_id` plus the desired fields (name, score, rank, territory, observed capability, confidence). Retrying the same desired state produces the same key even though `sync_timestamp` changes. The previous recorded build yielded 361 priority accounts, 358 creates, 3 updates, 0 unchanged, 1 CRM-only ignored, 361 payloads. The three existing records were missing fields that the sync writes; Asadito also had a changed fit score. The clarified field name and values need a fresh warehouse build before those counts are reconfirmed. Two runs with the same fixed timestamp produce byte-identical payloads.

Production would add OAuth/secrets, a real CRM client, batching, rate limits, retries with a dead-letter path, and an audit log. The point of the simulation is the boundary: the warehouse computes the desired state; the edge computes the diff and performs idempotent upserts.

## 6d. CRM identity resolution

[`scripts/resolve_identities.py`](../scripts/resolve_identities.py) writes a 2,644-row mapping seed from `dim_account` and `seeds/mock_crm_accounts.csv`. Matching is one-to-one and waterfalled:

1. exact normalized domain (confidence 100);
2. exact phone (last ten digits) plus normalized address (confidence 100);
3. fuzzy name + geo, with `confidence = 100 × (0.70 × name_similarity + 0.30 × max(0, 1 − distance/500))`.

The fuzzy stage requires name similarity ≥ 0.55 and distance ≤ 500 m. Candidates below 95 are still mapped but carry `needs_human_review = true`. Unmatched accounts keep a row with a null `crm_account_id`, confidence 0, and method `unmatched`; they are not review cases because there is no candidate. CRM-only records are ignored and counted in the run summary.

Current result: 6 matches (2 exact domain, 1 exact phone+address, 3 fuzzy), 2,638 unmatched, 3 review candidates, 1 CRM-only. `models/marts/crm_identity_map.sql` inner-joins the mapping to `dim_account`, so live is 2,644 rows and the 200-account sample map is 200 rows. The resolution seed is committed for clean-clone builds; the script is the generator, not a live CRM call.

## 7. Incremental strategy

`fct_lifecycle_event` is incremental with `delete+insert` on `unique_key='event_id'` and `on_schema_change='append_new_columns'`.

`merge` is not used. On Postgres, dbt's merge path has edge cases around duplicate source keys and is less predictable across adapter versions. `delete+insert` is deterministic: delete the keys present in the batch, insert the batch, commit. For an event spine with a deterministic UUID per event, that is sufficient and easy to reason about.

## 8. Offline sample path

The handoff asks for a 200-account sample and a clean-clone build. `--select sample*` alone only selects the seed, so the implemented path is a `use_sample_data` var that switches the **source identifiers** to sample seed tables:

| Source | Live | Sample |
|---|---|---|
| `raw.osm_restaurants` | `raw.osm_restaurants` | `staging.raw_accounts_sample` |
| `raw.website_signals` | `raw.website_signals` | `staging.website_signals_sample` |
| `raw.lifecycle_events` | `raw.lifecycle_events` | `staging.lifecycle_events_sample` |

The sample is 200 clusters (all 10 merges + 190 deterministic singletons), 210 raw rows, 119 signal rows, and 123 synthetic lifecycle events. The lifecycle seed is generated from the **sample deduped account ids**, not the live account table, so relationships line up. `extract/build_sample_seeds.py` implements the two-pass generation; the committed seeds are the result.

Build:

```bash
dbt seed --profiles-dir . --full-refresh
dbt build --profiles-dir . --full-refresh --vars '{use_sample_data: true}'
```

Verified on the committed seeds: 200 accounts, 123 events, 197-row sales queue, 7-row CS queue, 200-row identity map, 6-row funnel, **167/167 tests, 0 warnings**. The sample build still needs a Postgres target (dbt seeds into it), but it makes no Overpass or website requests and does not depend on the live raw tables. On a database that already contains the live marts, `--full-refresh` is required so the incremental event fact is replaced rather than merged with live events.

## 8a. Phase 6 verification

- Live `dbt build`: **167/167, 0 warnings, 146 data tests**. The committed log is [`docs/dbt_test_output.txt`](dbt_test_output.txt).
- Offline sample build: **167/167, 0 warnings** from 200 accounts, 123 events, a 197-row sales queue, a 7-row CS queue, and a 200-row identity map. The committed log is [`docs/sample_build_output.txt`](sample_build_output.txt).
- `fct_lifecycle_event` is incremental with `delete+insert`; a second run kept 1,636 rows and 1,636 distinct event IDs.
- `tests/assert_lifecycle_stage_order.sql` and the custom `tests/generic/between.sql` test both pass.
- Monitoring returns expected alerts, not pipeline errors: territory `Unknown` 17.8%, `full_address` null 13.6%, confirmed signal coverage 37.2%. Dedup duplicates, orphan events, out-of-order events, duplicate event pairs, fit-score range, and queue reconciliation are clean. `public` has zero base tables.
- Credential scan of tracked files finds no secrets; `.env` is ignored.

The remaining honest caveats are the dedup rate/recall (0.38%, unmeasured recall), the 37.3% signal-unknown population, the 17.8% territory `Unknown` bucket, and the raw-HTML blind spot for JavaScript-injected ordering.

## 9. Spec deviations and open issues

- **OSM primary key.** OSM IDs are unique per element type, not globally: node `123` and way `123` can both exist in the same extract. The spec's `PRIMARY KEY (osm_id)` would reject a legitimate record. The implementation uses a composite key / `osm_uid` (`osm_type || ':' || osm_id`) and keeps `osm_id` as a bigint for traceability. This is a correctness fix, flagged rather than silently applied.
- **Direct connection fallback.** The project does not implement one. If the session pooler is unreachable, the correct response is to fix the network or the pooler setting, not to fall back to an IPv6-only host that will fail intermittently.
- **Volume gate.** If the bbox returns more than 2,000 elements, Phase 1 stops and reports the count rather than truncating. All 2,654 post-filter records were loaded for this run after reviewing the scope: the cap was a heuristic, and a complete bbox is a stronger claim than a sample. A deterministic geographic sub-sample remains the fallback if the scope is ever narrowed.
- **Phase 3 fetch cap.** The domain cap is 2,000, not 1,000. At roughly 2,650 accounts with a 60–70% website rate, the expected domain count is 1,600–1,850; the exact count is reported at the Phase 3 gate before any fetches start. Fetches are sequential with a polite delay, so a one-time run is roughly an hour.
- **Overpass endpoint.** The primary `overpass-api.de` interpreter returned HTTP 502 on the first full request. The extractor accepts an `OVERPASS_URL` override so a public mirror can be used without changing the query. The gate report names the endpoint used; the data is OpenStreetMap either way.
- **Fit-score practical maximum is 90.** The spec's weights sum to 100, but first-party ordering and delivery-marketplace-only are mutually exclusive. The rubric keeps the exact weights and the 100 cap; no account can score above 90. This is documented in the table and the one-paragraph explanation.
- **Third-party website pages are skipped.** Yelp, Facebook, Instagram, and OpenTable pages are written with `fetch_status='skipped_third_party'`, not fetched. This respects source terms and avoids treating a platform page as the restaurant's homepage. It is a deliberate deviation from "fetch every website."
- **Territory has an Unknown bucket.** 470 accounts (17.8%) lack both a usable postcode and city. They are retained as `Unknown` rather than dropped; the monitoring check alerts on the Unknown share because the null rate alone would be zero.
- **Dedup rate is 0.38%.** 10 merges from 2,654 raw records; the stratified audit found 10/10 merge precision and 40/40 split precision, but recall is unmeasured. The low rate is plausible for this query and documented as a limitation, not treated as proof of completeness.
- **`days_since_last_order`.** The lifecycle generator emits a `first_order` event, not a stream of repeat orders. Until repeat order events exist, `days_since_last_order` and `days_since_first_order` are the same quantity. The column comment says so; the alternative would be inventing order history that the spec does not ask for.

## 10. What I would do with 10x the time

- Replace the single Overpass pull with an incremental OSM change feed (`osmChange`) and a snapshot history, so closures and renames are observable rather than silently overwritten.
- Add a real geocoder with a license that permits caching, and measure dedup against a hand-labelled sample instead of a 50-cluster spot check.
- Crawl more than the homepage, with a per-domain politeness budget queried from `robots.txt`, and store script URLs as evidence for JS-injected ordering widgets.
- Move the lifecycle generator behind an event contract (schema + ordered-stage validator) so synthetic and future real events share one interface.
- Add CI: `dbt build` against a disposable Postgres, `sqlfluff`, and a check that `.env` and service-role keys never enter the diff.
- Replace the snapshot-table monitoring with a proper metrics store and alert routing, with run IDs so a failed load is attributable.
