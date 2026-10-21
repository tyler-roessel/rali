with source as (
    select * from {{ source('raw', 'osm_restaurants') }}
),

renamed as (
    select
        osm_uid,
        osm_id::bigint as osm_id,
        lower(trim(osm_type)) as osm_type,
        nullif(trim(name), '') as name,
        nullif(trim(cuisine), '') as cuisine,
        nullif(trim(addr_street), '') as addr_street,
        nullif(trim(addr_housenumber), '') as addr_housenumber,
        -- "3661 3663" and "3661-3663" are ranges; "3661A" is a unit suffix.
        -- Keep the first numeric token for matching, preserve the raw value for display.
        nullif(
            regexp_replace(nullif(trim(addr_housenumber), ''), '^(\d+).*$', '\1'),
            ''
        ) as addr_housenumber_norm,
        nullif(trim(addr_city), '') as addr_city,
        nullif(trim(addr_postcode), '') as addr_postcode,
        nullif(trim(phone), '') as phone,
        nullif(trim(website), '') as website,
        nullif(trim(opening_hours), '') as opening_hours,
        nullif(trim(brand), '') as brand,
        nullif(trim(operator), '') as operator,
        lat::double precision as lat,
        lon::double precision as lon,
        loaded_at
    from source
),

normalized as (
    select
        *,
        {{ normalize_name('name') }} as normalized_name,
        {{ normalize_address('addr_housenumber_norm', 'addr_street', 'addr_city', 'addr_postcode') }} as normalized_address,
        {{ normalize_address('addr_housenumber_norm', 'addr_street', 'null::text', 'null::text') }} as normalized_street,
        case
            when nullif(trim(concat_ws(' ', addr_housenumber, addr_street)), '') is null then null
            else concat_ws(
                ', ',
                nullif(trim(concat_ws(' ', addr_housenumber, addr_street)), ''),
                nullif(trim(addr_city), ''),
                nullif(trim(addr_postcode), '')
            )
        end as full_address,
        (website is not null) as has_website,
        (phone is not null) as has_phone
    from renamed
),

final as (
    select
        *,
        nullif(trim(regexp_replace(normalized_street, '^\d+\s+', '')), '') as normalized_street_name
    from normalized
)

select * from final
