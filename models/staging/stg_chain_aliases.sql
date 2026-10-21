select
    trim(chain_brand) as chain_brand,
    trim(alias) as alias,
    {{ normalize_name('alias') }} as normalized_alias
from {{ ref('chain_name_lookup') }}
where nullif(trim(alias), '') is not null
