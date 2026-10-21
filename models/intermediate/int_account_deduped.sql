with survivors as (
    select * from {{ ref('int_account_clusters') }}
    where survivor_rank = 1
),

chain_aliases as (
    select
        normalized_alias,
        min(chain_brand) as chain_brand
    from {{ ref('stg_chain_aliases') }}
    where normalized_alias is not null
    group by normalized_alias
)

select
    uuid_generate_v5(uuid_ns_url(), 'rali:account:' || survivors.dedup_key) as account_id,
    survivors.dedup_key,
    survivors.address_key,
    survivors.osm_uid,
    survivors.osm_id,
    survivors.osm_type,
    survivors.name,
    survivors.cuisine,
    survivors.addr_street,
    survivors.addr_housenumber,
    survivors.addr_city,
    survivors.addr_postcode,
    survivors.phone,
    survivors.website,
    survivors.opening_hours,
    survivors.brand,
    survivors.operator,
    survivors.lat,
    survivors.lon,
    survivors.normalized_name,
    survivors.normalized_street,
    survivors.normalized_street_name,
    survivors.normalized_address,
    survivors.full_address,
    survivors.has_website,
    survivors.has_phone,
    survivors.source_record_count,
    survivors.match_rule,
    (chain_aliases.chain_brand is not null) as is_chain,
    chain_aliases.chain_brand
from survivors
left join chain_aliases
    on survivors.normalized_name = chain_aliases.normalized_alias
