with base as (
    select *
    from {{ ref('dim_account') }}
    where not is_chain
),

ranked as (
    select
        *,
        row_number() over (
            order by fit_score desc, has_website desc, name
        ) as rank,
        round(
            100.0 * avg(case when signal_confidence = 'confirmed' then 1 else 0 end) over (),
            1
        ) as signal_coverage_pct
    from base
)

select
    account_id,
    name as account_name,
    territory,
    cuisine,
    fit_score,
    fit_score_band,
    case
        when has_online_ordering then 'ordering_fragment_observed'
        when delivery_marketplace_only then 'delivery_fragment_without_ordering_match'
        when has_reservations then 'reservation_fragment_observed'
        when has_website then 'website_recorded_capability_unknown'
        else 'website_not_recorded'
    end as observed_capability,
    rank,
    case
        when delivery_marketplace_only then 'Verify direct-order flow and CRM status; discuss guest ownership if relevant'
        when has_online_ordering then 'Review ordering and marketing stack; explore consolidation if relevant'
        when has_reservations then 'Review discovery-to-reservation and guest-marketing workflow'
        when has_website then 'Review menu visibility and guest-contact capture'
        else 'Verify website and account identity before outreach'
    end as suggested_action,
    signal_confidence,
    failure_class,
    signal_coverage_pct,
    has_website,
    has_online_ordering,
    has_reservations,
    delivery_marketplace_only,
    website,
    phone
from ranked
