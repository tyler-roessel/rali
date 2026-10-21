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
        when has_online_ordering then 'first_party_ordering'
        when delivery_marketplace_only then 'delivery_marketplace_dependent'
        when has_reservations then 'reservation_led'
        when has_website then 'web_presence_no_ordering'
        else 'no_web_signal'
    end as intent_signal,
    rank,
    case
        when delivery_marketplace_only then 'Displace marketplace: pitch commission savings'
        when fit_score >= 80 and has_online_ordering then 'Expand: consolidate ordering'
        when fit_score >= 80 then 'Priority demo: pitch direct ordering'
        when fit_score >= 60 then 'Nurture: qualify the operator'
        else 'Monitor: low fit'
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
