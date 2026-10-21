-- Fails if any account has an event timestamp earlier than the event that
-- precedes it in the lifecycle stage order. Stage order is explicit rather
-- than inferred from timestamps, otherwise the test would be tautological.
with staged as (
    select
        account_id,
        event_name,
        event_timestamp,
        case event_name
            when 'prospect_created' then 1
            when 'demo_booked' then 2
            when 'closed_won' then 3
            when 'onboarded' then 4
            when 'first_order' then 5
            when '30_day_active' then 6
            when 'support_ticket' then 7
            when 'renewal_due' then 8
            else 99
        end as stage_rank
    from {{ source('raw', 'lifecycle_events') }}
),

ordered as (
    select
        account_id,
        event_name,
        event_timestamp,
        lag(event_timestamp) over (
            partition by account_id
            order by stage_rank, event_timestamp
        ) as previous_timestamp
    from staged
)

select *
from ordered
where previous_timestamp is not null
  and event_timestamp < previous_timestamp
