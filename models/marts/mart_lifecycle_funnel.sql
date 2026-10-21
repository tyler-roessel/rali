with mapping as (
    select * from {{ ref('lifecycle_mapping') }}
),

stages as (
    select distinct lifecycle_stage, stage_order
    from mapping
),

stage_arrivals as (
    select
        events.account_id,
        mapping.lifecycle_stage,
        mapping.stage_order,
        min(events.event_timestamp) as arrived_at
    from {{ ref('fct_lifecycle_event') }} events
    join mapping
        on events.event_name = mapping.event_name
    where mapping.counts_toward_funnel
    group by events.account_id, mapping.lifecycle_stage, mapping.stage_order
),

reached as (
    select
        arrivals.lifecycle_stage,
        arrivals.stage_order,
        count(distinct arrivals.account_id) as accounts_reached,
        round(
            percentile_cont(0.5) within group (
                order by extract(epoch from (arrivals.arrived_at - previous.arrived_at)) / 86400.0
            )::numeric,
            1
        ) as median_days_from_previous
    from stage_arrivals arrivals
    left join stage_arrivals previous
        on arrivals.account_id = previous.account_id
        and previous.stage_order = arrivals.stage_order - 1
    group by arrivals.lifecycle_stage, arrivals.stage_order
),

funnel as (
    select
        stages.lifecycle_stage,
        stages.stage_order,
        coalesce(reached.accounts_reached, 0) as accounts_reached,
        reached.median_days_from_previous,
        lag(coalesce(reached.accounts_reached, 0)) over (order by stages.stage_order) as previous_stage_accounts,
        first_value(coalesce(reached.accounts_reached, 0)) over (order by stages.stage_order) as lead_accounts
    from stages
    left join reached
        on stages.lifecycle_stage = reached.lifecycle_stage
        and stages.stage_order = reached.stage_order
)

select
    lifecycle_stage,
    stage_order,
    accounts_reached,
    case
        when stage_order = 1 then null
        else round(accounts_reached::numeric / nullif(previous_stage_accounts, 0), 4)
    end as conversion_from_previous,
    round(accounts_reached::numeric / nullif(lead_accounts, 0), 4) as conversion_from_lead,
    median_days_from_previous
from funnel
order by stage_order
