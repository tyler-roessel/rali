with won as (
    select
        account_id,
        event_id,
        event_timestamp as closed_won_at,
        coalesce((event_properties ->> 'handoff_leak')::boolean, false) as is_explicit_leak,
        source_system
    from {{ ref('fct_lifecycle_event') }}
    where event_name = 'closed_won'
),

onboarded as (
    select distinct account_id
    from {{ ref('fct_lifecycle_event') }}
    where event_name = 'onboarded'
)

select
    account.account_id,
    account.name as account_name,
    account.territory,
    coalesce(routing.owner_key, 'cx_triage') as owner_key,
    won.closed_won_at,
    won.closed_won_at + interval '24 hours' as handoff_due_at,
    'closed_won_without_onboarding' as exception_type,
    won.is_explicit_leak,
    won.source_system,
    md5(won.event_id::text) as notification_key,
    'Confirm the Sales-to-CX handoff and assign an onboarding owner' as next_action
from won
join {{ ref('dim_account') }} account
    on won.account_id = account.account_id
left join onboarded
    on won.account_id = onboarded.account_id
left join {{ ref('handoff_owner_routing') }} routing
    on account.territory = routing.territory
where onboarded.account_id is null
