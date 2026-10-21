with dedup as (
    select * from {{ ref('int_account_deduped') }}
),

cuisine_tokens as (
    select
        dedup.account_id,
        lower(trim(tokens.token)) as cuisine_token
    from dedup
    cross join lateral regexp_split_to_table(
        coalesce(dedup.cuisine, ''),
        '\s*;\s*'
    ) as tokens(token)
),

cuisine_flags as (
    select
        tokens.account_id,
        bool_or(coalesce(lookup.is_high_fit, false)) as cuisine_high_fit
    from cuisine_tokens tokens
    left join {{ ref('cuisine_fit_lookup') }} lookup
        on tokens.cuisine_token = lower(trim(lookup.cuisine_token))
    group by tokens.account_id
),

joined as (
    select
        dedup.account_id,
        dedup.dedup_key,
        dedup.osm_uid,
        dedup.name,
        dedup.cuisine,
        dedup.full_address,
        dedup.addr_city,
        dedup.addr_postcode,
        dedup.lat,
        dedup.lon,
        dedup.website,
        {{ website_domain('dedup.website') }} as website_domain,
        dedup.phone,
        dedup.has_website,
        dedup.has_phone,
        dedup.is_chain,
        dedup.chain_brand,
        dedup.normalized_name,
        dedup.source_record_count,
        dedup.match_rule,
        {{ territory('dedup.addr_postcode', 'dedup.addr_city') }} as territory,
        coalesce(signals.signal_confidence, 'unknown_unreachable') as signal_confidence,
        signals.failure_class,
        coalesce(signals.has_online_ordering, false) as has_online_ordering,
        coalesce(signals.has_reservations, false) as has_reservations,
        coalesce(cardinality(signals.delivery_marketplaces), 0) > 0 as has_delivery,
        coalesce(signals.delivery_marketplaces, '{}'::text[]) as delivery_marketplaces,
        signals.site_platform,
        coalesce(flags.cuisine_high_fit, false) as cuisine_high_fit
    from dedup
    left join cuisine_flags flags
        on dedup.account_id = flags.account_id
    left join {{ ref('stg_website_signals') }} signals
        on {{ website_domain('dedup.website') }} = signals.domain
),

points as (
    select
        *,
        case when not is_chain then 25 else 0 end as fit_independent_points,
        case when has_website then 15 else 0 end as fit_website_points,
        case when has_online_ordering then 15 else 0 end as fit_ordering_points,
        case when has_reservations then 10 else 0 end as fit_reservations_points,
        case when cuisine_high_fit then 15 else 0 end as fit_cuisine_points,
        case when has_phone then 10 else 0 end as fit_phone_points,
        case
            when has_delivery and not has_online_ordering then 10
            else 0
        end as fit_delivery_only_points
    from joined
),

scored as (
    select
        *,
        least(
            100,
            fit_independent_points
            + fit_website_points
            + fit_ordering_points
            + fit_reservations_points
            + fit_cuisine_points
            + fit_phone_points
            + fit_delivery_only_points
        ) as fit_score
    from points
)

select
    account_id,
    dedup_key,
    osm_uid,
    name,
    cuisine,
    full_address,
    addr_city,
    addr_postcode,
    lat,
    lon,
    website,
    website_domain,
    phone,
    has_website,
    has_phone,
    is_chain,
    chain_brand,
    normalized_name,
    source_record_count,
    match_rule,
    territory,
    signal_confidence,
    failure_class,
    has_online_ordering,
    has_reservations,
    has_delivery,
    (has_delivery and not has_online_ordering) as delivery_marketplace_only,
    delivery_marketplaces,
    site_platform,
    cuisine_high_fit,
    fit_independent_points,
    fit_website_points,
    fit_ordering_points,
    fit_reservations_points,
    fit_cuisine_points,
    fit_phone_points,
    fit_delivery_only_points,
    fit_score,
    case
        when fit_score >= 80 then 'priority'
        when fit_score >= 60 then 'nurture'
        else 'low'
    end as fit_score_band
from scored
