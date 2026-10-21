with source as (
    select * from {{ source('raw', 'website_signals') }}
)

select
    domain,
    has_website,
    has_online_ordering,
    online_ordering_vendor,
    has_reservations,
    reservation_vendor,
    delivery_marketplaces::text[] as delivery_marketplaces,
    site_platform,
    signal_confidence,
    failure_class,
    fetch_status,
    http_status,
    final_url,
    page_title,
    evidence,
    error_detail,
    account_count,
    fetched_at
from source
