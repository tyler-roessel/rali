{{ config(materialized='view') }}

-- A research worklist, not a send list. The CRM map is a mock and cannot
-- establish customer status in the platform's private systems.
with shared_domains as (
    select
        account.website_domain,
        count(distinct account.account_id) as location_group_candidate_count
    from {{ ref('dim_account') }} account
    join {{ ref('stg_website_signals') }} signals
        on account.website_domain = signals.domain
    where signals.fetch_status <> 'skipped_third_party'
    group by account.website_domain
),

research as (
    select
        sales.account_id,
        sales.account_name,
        sales.territory,
        sales.rank as queue_rank,
        sales.fit_score as demo_fit_score,
        sales.fit_score_band as demo_fit_band,
        sales.website,
        account.website_domain,
        sales.observed_capability,
        sales.signal_confidence,
        sales.failure_class,
        signals.fetch_status,
        signals.fetched_at,
        signals.evidence as homepage_evidence_fragments,
        signals.online_ordering_vendor as observed_ordering_vendor,
        signals.reservation_vendor as observed_reservation_vendor,
        signals.delivery_marketplaces as observed_delivery_marketplaces,
        coalesce(shared_domains.location_group_candidate_count, 0) as location_group_candidate_count,
        coalesce(shared_domains.location_group_candidate_count, 0) > 1 as possible_multi_location_group,
        case
            when identity.needs_human_review then 'demo_identity_review'
            when identity.is_matched then 'matched_in_demo_crm'
            else 'not_matched_in_demo_crm'
        end as demo_crm_review_state
    from {{ ref('mart_sales_queue') }} sales
    join {{ ref('dim_account') }} account
        on sales.account_id = account.account_id
    left join {{ ref('stg_website_signals') }} signals
        on account.website_domain = signals.domain
    left join shared_domains
        on account.website_domain = shared_domains.website_domain
    left join {{ ref('crm_identity_map') }} identity
        on sales.account_id = identity.account_id
)

select
    *,
    case
        when observed_capability = 'delivery_fragment_without_ordering_match'
            then 'Explore whether direct ordering and guest ownership are priorities; homepage scan may have missed an ordering flow'
        when observed_capability = 'ordering_fragment_observed'
            then 'Explore whether ordering, menu, and guest marketing are fragmented across tools'
        when observed_capability = 'reservation_fragment_observed'
            then 'Explore discovery, reservation, and repeat-visit workflows'
        when observed_capability = 'website_recorded_capability_unknown'
            then 'Inspect menu, ordering, and guest-contact paths manually'
        else 'Verify current website and account identity before forming a product hypothesis'
    end as use_case_hypothesis,
    case
        when demo_crm_review_state = 'demo_identity_review'
            then 'Resolve account identity, inspect live site, and check private CRM before any outreach'
        when possible_multi_location_group
            then 'Verify whether shared-domain locations have one buyer; inspect live site and private CRM'
        else 'Inspect live site and check private CRM for customer, open opportunity, and suppression status'
    end as next_research_step,
    false as outreach_ready
from research
