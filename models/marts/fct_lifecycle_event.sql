{{ config(
    materialized='incremental',
    unique_key='event_id',
    incremental_strategy='delete+insert',
    on_schema_change='append_new_columns'
) }}

select
    event_id::uuid as event_id,
    account_id::uuid as account_id,
    event_name,
    event_timestamp::timestamptz as event_timestamp,
    event_timestamp::date as event_date,
    source_system,
    event_properties::jsonb as event_properties,
    case event_name
        when 'prospect_created' then 1
        when 'demo_booked' then 2
        when 'closed_won' then 3
        when 'onboarded' then 4
        when 'first_order' then 5
        when '30_day_active' then 6
        when 'support_ticket' then 7
        when 'renewal_due' then 8
    end as stage_rank
from {{ source('raw', 'lifecycle_events') }}
