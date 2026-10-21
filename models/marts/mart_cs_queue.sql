with base as (
    select
        account.account_id,
        account.name,
        account.territory,
        health.onboarded_date,
        health.days_since_first_order,
        health.adoption_score,
        health.support_risk,
        health.renewal_risk,
        health.renewal_date,
        health.expansion_flag,
        health.is_at_risk,
        account.signal_confidence,
        account.failure_class
    from {{ ref('dim_account') }} account
    join {{ ref('fct_account_health') }} health
        on account.account_id = health.account_id
    where health.onboarded_date is not null
),

ranked as (
    select
        *,
        row_number() over (
            order by
                case support_risk when 'high' then 0 when 'medium' then 1 else 2 end,
                case renewal_risk when 'high' then 0 when 'medium' then 1 else 2 end,
                adoption_score asc,
                onboarded_date
        ) as cs_rank,
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
    onboarded_date,
    days_since_first_order,
    adoption_score,
    support_risk,
    renewal_risk,
    renewal_date,
    expansion_flag,
    is_at_risk,
    cs_rank,
    case
        when support_risk = 'high' then 'Executive check-in + support triage'
        when support_risk = 'medium' then 'Support check-in'
        when renewal_risk = 'high' then 'Renewal save play'
        when expansion_flag then 'Expansion review'
        when adoption_score < 50 then 'Onboarding recovery'
        else 'Quarterly business review'
    end as recommended_play,
    signal_confidence,
    failure_class,
    signal_coverage_pct
from ranked
