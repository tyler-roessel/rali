with accounts as (
    select account_id from {{ ref('dim_account') }}
),

events as (
    select
        account_id,
        max(event_timestamp) filter (where event_name = 'onboarded') as onboarded_at,
        max(event_timestamp) filter (where event_name = 'first_order') as first_order_at,
        max(event_timestamp) filter (where event_name = '30_day_active') as thirty_day_at,
        max(event_timestamp) filter (where event_name = 'support_ticket') as support_ticket_at,
        max(event_timestamp) filter (where event_name = 'renewal_due') as renewal_due_at
    from {{ ref('fct_lifecycle_event') }}
    group by account_id
),

metrics as (
    select
        accounts.account_id,
        events.onboarded_at::date as onboarded_date,
        events.first_order_at::date as first_order_date,
        events.first_order_at::date as last_order_date,
        events.renewal_due_at::date as renewal_due_date,
        (events.first_order_at::date - events.onboarded_at::date) as days_to_first_order,
        (current_date - events.first_order_at::date) as days_since_first_order,
        (current_date - events.first_order_at::date) as days_since_last_order,
        coalesce(
            events.renewal_due_at::date,
            (events.onboarded_at + interval '365 days')::date
        ) as renewal_date,
        (events.onboarded_at is not null) as has_onboarded,
        (events.first_order_at is not null) as has_first_order,
        (events.thirty_day_at is not null) as has_30_day,
        (events.support_ticket_at is not null) as has_support_ticket,
        (events.renewal_due_at is not null) as has_renewal_due,
        case
            when events.onboarded_at is null then 0
            else least(
                100,
                25
                + case when events.first_order_at is not null then 25 else 0 end
                + case when events.thirty_day_at is not null then 25 else 0 end
                + case when events.support_ticket_at is null then 15 else 0 end
                + case
                    when events.first_order_at is not null
                         and (events.first_order_at::date - events.onboarded_at::date) <= 7
                    then 10
                    else 0
                  end
            )
        end as adoption_score
    from accounts
    left join events
        on accounts.account_id = events.account_id
),

scored as (
    select
        *,
        case
            when has_support_ticket and adoption_score < 50 then 'high'
            when has_support_ticket then 'medium'
            else 'low'
        end as support_risk,
        case
            when has_renewal_due and not has_first_order then 'high'
            when has_renewal_due then 'medium'
            else 'low'
        end as renewal_risk
    from metrics
)

select
    account_id,
    onboarded_date,
    first_order_date,
    last_order_date,
    renewal_due_date,
    renewal_date,
    days_to_first_order,
    days_since_first_order,
    days_since_last_order,
    adoption_score,
    has_onboarded,
    has_first_order,
    has_30_day,
    has_support_ticket,
    has_renewal_due,
    support_risk,
    renewal_risk,
    (has_30_day and adoption_score >= 75 and not has_support_ticket) as expansion_flag,
    (
        has_onboarded
        and (
            support_risk in ('high', 'medium')
            or renewal_risk = 'high'
            or adoption_score < 50
        )
    ) as is_at_risk
from scored
