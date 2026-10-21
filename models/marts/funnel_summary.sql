with events as (
    select account_id, event_name, event_timestamp
    from {{ ref('fct_lifecycle_event') }}
),

pivoted as (
    select
        account_id,
        max(event_timestamp) filter (where event_name = 'prospect_created') as prospect_at,
        max(event_timestamp) filter (where event_name = 'demo_booked') as demo_at,
        max(event_timestamp) filter (where event_name = 'closed_won') as closed_at,
        max(event_timestamp) filter (where event_name = 'onboarded') as onboarded_at,
        max(event_timestamp) filter (where event_name = 'first_order') as first_order_at,
        max(event_timestamp) filter (where event_name = '30_day_active') as thirty_day_at
    from events
    group by account_id
),

counts as (
    select
        count(*) filter (where prospect_at is not null) as prospects,
        count(*) filter (where demo_at is not null) as demos,
        count(*) filter (where closed_at is not null) as won,
        count(*) filter (where onboarded_at is not null) as onboarded,
        count(*) filter (where first_order_at is not null) as first_orders,
        count(*) filter (where thirty_day_at is not null) as thirty_day
    from pivoted
),

stages as (
    select 1 as stage_order, 'prospect_created' as stage_name, prospects as accounts_reached,
           null::numeric as conversion_from_previous, null::numeric as median_days_from_previous
    from counts
    union all
    select 2, 'demo_booked', demos,
           round(demos::numeric / nullif(prospects, 0), 4),
           (
               select round(
                   percentile_cont(0.5) within group (
                       order by extract(epoch from (demo_at - prospect_at)) / 86400.0
                   )::numeric,
                   1
               )
               from pivoted
               where demo_at is not null and prospect_at is not null
           )
    from counts
    union all
    select 3, 'closed_won', won,
           round(won::numeric / nullif(demos, 0), 4),
           (
               select round(
                   percentile_cont(0.5) within group (
                       order by extract(epoch from (closed_at - demo_at)) / 86400.0
                   )::numeric,
                   1
               )
               from pivoted
               where closed_at is not null and demo_at is not null
           )
    from counts
    union all
    select 4, 'onboarded', onboarded,
           round(onboarded::numeric / nullif(won, 0), 4),
           (
               select round(
                   percentile_cont(0.5) within group (
                       order by extract(epoch from (onboarded_at - closed_at)) / 86400.0
                   )::numeric,
                   1
               )
               from pivoted
               where onboarded_at is not null and closed_at is not null
           )
    from counts
    union all
    select 5, 'first_order', first_orders,
           round(first_orders::numeric / nullif(onboarded, 0), 4),
           (
               select round(
                   percentile_cont(0.5) within group (
                       order by extract(epoch from (first_order_at - onboarded_at)) / 86400.0
                   )::numeric,
                   1
               )
               from pivoted
               where first_order_at is not null and onboarded_at is not null
           )
    from counts
    union all
    select 6, '30_day_active', thirty_day,
           round(thirty_day::numeric / nullif(first_orders, 0), 4),
           (
               select round(
                   percentile_cont(0.5) within group (
                       order by extract(epoch from (thirty_day_at - first_order_at)) / 86400.0
                   )::numeric,
                   1
               )
               from pivoted
               where thirty_day_at is not null and first_order_at is not null
           )
    from counts
)

select
    stage_name,
    stage_order,
    accounts_reached,
    conversion_from_previous,
    round(accounts_reached::numeric / nullif((select prospects from counts), 0), 4) as conversion_from_prospect,
    median_days_from_previous
from stages
order by stage_order
