with base as (
    select * from {{ ref('stg_restaurants') }}
),

street_groups as (
    select
        normalized_name,
        normalized_street,
        count(distinct nullif(addr_city, '')) as city_count,
        count(distinct nullif(addr_postcode, '')) as postcode_count
    from base
    where normalized_street is not null
    group by normalized_name, normalized_street
),

street_name_groups as (
    select
        normalized_name,
        normalized_street_name,
        count(distinct nullif(addr_housenumber_norm, '')) as house_count,
        count(distinct nullif(addr_city, '')) as city_count,
        count(distinct nullif(addr_postcode, '')) as postcode_count,
        min(nullif(addr_city, '')) as city_canonical,
        min(nullif(addr_postcode, '')) as postcode_canonical
    from base
    where normalized_street_name is not null
    group by normalized_name, normalized_street_name
),

addressed as (
    select
        base.*,
        case
            -- Same name and same street, with at most one distinct house number.
            -- Catches a missing or partial house number without merging two
            -- different addresses on the same street.
            when base.normalized_street_name is not null
                and street_name_groups.house_count <= 1
                and street_name_groups.city_count <= 1
                and street_name_groups.postcode_count <= 1
                then 'street_name|'
                    || base.normalized_name
                    || '|'
                    || base.normalized_street_name
                    || '|'
                    || coalesce(street_name_groups.city_canonical, '')
                    || '|'
                    || coalesce(street_name_groups.postcode_canonical, '')

            -- Same name and same house+street. City/postcode may be missing on
            -- either record, but two distinct non-null values are a conflict.
            when base.normalized_street is not null
                and street_groups.city_count <= 1
                and street_groups.postcode_count <= 1
                then 'street|' || base.normalized_name || '|' || base.normalized_street

            when base.normalized_address is not null
                then 'address|' || base.normalized_name || '|' || base.normalized_address
            when base.lat is not null and base.lon is not null
                then 'geo|'
                    || base.normalized_name
                    || '|'
                    || round(base.lat::numeric, 4)::text
                    || '|'
                    || round(base.lon::numeric, 4)::text
            else 'uid|' || base.osm_uid
        end as address_key,
        case
            when base.normalized_street_name is not null
                and street_name_groups.house_count <= 1
                and street_name_groups.city_count <= 1
                and street_name_groups.postcode_count <= 1
                then 'street_name'
            when base.normalized_street is not null
                and street_groups.city_count <= 1
                and street_groups.postcode_count <= 1
                then 'street_address'
            when base.normalized_address is not null then 'full_address'
            when base.lat is not null and base.lon is not null then 'geo_4dp'
            else 'uid_fallback'
        end as address_match_rule
    from base
    left join street_groups
        on base.normalized_name = street_groups.normalized_name
        and base.normalized_street = street_groups.normalized_street
    left join street_name_groups
        on base.normalized_name = street_name_groups.normalized_name
        and base.normalized_street_name = street_name_groups.normalized_street_name
),

multi_names as (
    select normalized_name
    from addressed
    group by normalized_name
    having count(*) > 1
),

-- A proximity edge only exists when the name matches exactly and the two
-- records are within ~50 m. It supplements the address rules, it does not
-- replace them: different addresses on the same street remain separate unless
-- they are both close and name-identical. Scale longitude at each pair's mean
-- latitude so the threshold remains local to the market being processed.
geo_pairs as (
    select
        a.address_key as key_a,
        b.address_key as key_b,
        least(a.address_key, b.address_key) as geo_root
    from addressed a
    join multi_names
        on a.normalized_name = multi_names.normalized_name
    join addressed b
        on a.normalized_name = b.normalized_name
        and a.address_key < b.address_key
        and a.lat is not null
        and a.lon is not null
        and b.lat is not null
        and b.lon is not null
        and power((a.lat - b.lat) * 111000, 2)
            + power(
                (a.lon - b.lon) * 111000
                * cos(radians((a.lat + b.lat) / 2)),
                2
            )
            <= power(50, 2)
),

geo_roots as (
    select address_key, min(geo_root) as geo_root
    from (
        select key_a as address_key, geo_root from geo_pairs
        union all
        select key_b as address_key, geo_root from geo_pairs
    ) links
    group by address_key
),

merged as (
    select
        addressed.*,
        coalesce(geo_roots.geo_root, addressed.address_key) as dedup_key,
        case
            when geo_roots.geo_root is not null then 'geo_50m'
            else addressed.address_match_rule
        end as match_rule
    from addressed
    left join geo_roots
        on addressed.address_key = geo_roots.address_key
),

counted as (
    select
        *,
        count(*) over (partition by dedup_key) as source_record_count,
        row_number() over (
            partition by dedup_key
            order by
                (website is not null) desc,
                (phone is not null) desc,
                osm_id,
                osm_type,
                osm_uid
        ) as survivor_rank
    from merged
)

select * from counted
