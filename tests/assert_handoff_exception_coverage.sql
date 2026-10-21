with expected as (
    select account_id
    from {{ ref('fct_lifecycle_event') }}
    where event_name = 'closed_won'
    except
    select account_id
    from {{ ref('fct_lifecycle_event') }}
    where event_name = 'onboarded'
),

actual as (
    select account_id
    from {{ ref('mart_handoff_exceptions') }}
)

select 'missing_exception' as failure, account_id
from (select account_id from expected except select account_id from actual) missing
union all
select 'unexpected_exception' as failure, account_id
from (select account_id from actual except select account_id from expected) unexpected
