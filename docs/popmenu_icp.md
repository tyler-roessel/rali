# Popmenu ICP research layer

RALI is a Dallas pilot for a restaurant GTM workflow, not Popmenu's customer list or validated ICP. The independent full-service filter and fit score remain a demo rubric. Public Popmenu material supports a broader market: its [single-location](https://get.popmenu.com/en-gb/location/single-location), [2–10 location](https://get.popmenu.com/en-gb/location/2-to-10-locations), and [multi-location](https://get.popmenu.com/location/multi-location) pages describe different needs. Its [customer examples](https://get.popmenu.com/en-gb/client-highlights) include formats outside this pilot's cuisine filter. Existing digital tools are not automatically disqualifying; Popmenu also publishes a [Toast integration](https://get.popmenu.com/integrations/toast).

The [GTM Engineer posting](https://apply.workable.com/popmenu/j/0CC5B68239/) calls for a reliable restaurant account source, territory routing, fit and intent signals, CRM workflows, and Sales-to-CX handoffs. The [Dallas Account Executive posting](https://apply.workable.com/popmenu/j/ABFEC6B5A7) discusses owner-led restaurants and multi-location operators. These are product and role signals, not proof that any RALI account is qualified or in market.

The warehouse now models the Dallas market. The 2026-10-21 run used the Dallas bbox (`32.60,-96.99,33.02,-96.55`) and produced 1,479 accounts, 1,477 research-queue rows, and 125 rows with a possible shared-domain group; none is outreach-ready. The earlier Chicago extract survives only as the committed offline sample fixture and as the audit record behind the matching rules.

## What the view adds

`marts.mart_rep_research_queue` covers every existing sales-queue row. It retains score and rank, and adds:

| Column | Interpretation |
|---|---|
| `observed_capability`, `homepage_evidence_fragments`, vendor fields, `signal_confidence`, `fetch_status`, `fetched_at` | Homepage clues and collection limits. A missing fragment does not prove a missing capability. |
| `location_group_candidate_count`, `possible_multi_location_group` | Multiple map accounts share a fetched, non-platform domain. This does not merge locations or prove a common buyer. |
| `use_case_hypothesis` | A question for a rep to validate, never a diagnosis of pain or purchase intent. |
| `demo_crm_review_state` | Status against the small mock CRM only. An unmatched row says nothing about Popmenu's CRM. |
| `next_research_step`, `outreach_ready` | Manual website and actual CRM verification before outreach. `outreach_ready` is false for every row. |

The original `fit_score` still powers rank and appears as `demo_fit_score` here. It has not been calibrated to Popmenu outcomes. `observed_capability` replaces the former `intent_signal` label in the sales queue, mock reverse ETL, and inactive outbound template. The underlying homepage scan and score are unchanged.

## Rep workflow

1. Filter by territory and demo fit band. A higher score means inspect first, not send first. Dallas territory is a coarse ZIP/city bucket (Downtown, East, North, South, Metro, Other, Suburbs, Unknown); 45.0% of Dallas accounts have neither a usable ZIP nor a city and sit in `Unknown`.
2. Read evidence and fetch status. Open the live website to check menu, ordering, reservations, guest marketing, and whether the business is still operating.
3. If a possible multi-location group is flagged, verify the locations and buyer structure.
4. Check the actual Popmenu CRM for customer, opportunity, owner, duplicate, and suppression status. Resolve ambiguous identities. The mock CRM cannot perform this check.
5. Confirm a relevant use case before a human decides whether to contact the operator. This view sends no messages and changes no CRM records.

Example inspection query after a dbt build:

```sql
select queue_rank, account_name, territory, demo_fit_score,
       observed_capability, signal_confidence, homepage_evidence_fragments,
       possible_multi_location_group, demo_crm_review_state,
       use_case_hypothesis, next_research_step, outreach_ready
from marts.mart_rep_research_queue
where demo_fit_band = 'priority'
order by queue_rank
limit 25;
```

This addition uses existing map, homepage, and mock CRM data. It adds no crawler, live integration, external territory data, contact enrichment, or automated outreach. A different market requires a separate extract and validation pass; the Dallas extract has not been validated against Popmenu's private ICP.
