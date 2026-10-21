with mapping as (
    select * from {{ ref('crm_identity_resolution') }}
),

dim as (
    select
        account_id,
        name as account_name,
        website_domain,
        phone as warehouse_phone,
        normalized_address as warehouse_address,
        fit_score,
        territory
    from {{ ref('dim_account') }}
),

crm as (
    select
        crm_account_id,
        crm_name,
        domain as crm_domain,
        phone as crm_phone,
        address as crm_address
    from {{ ref('mock_crm_accounts') }}
)

select
    dim.account_id,
    dim.account_name,
    dim.website_domain,
    dim.warehouse_phone,
    dim.warehouse_address,
    dim.fit_score,
    dim.territory,
    mapping.crm_account_id,
    crm.crm_name,
    crm.crm_domain,
    crm.crm_phone,
    crm.crm_address,
    coalesce(mapping.match_method, 'unmatched') as match_method,
    coalesce(mapping.match_confidence, 0) as match_confidence,
    coalesce(mapping.needs_human_review, false) as needs_human_review,
    coalesce(mapping.match_evidence, 'no_candidate') as match_evidence,
    (mapping.crm_account_id is not null) as is_matched
from dim
left join mapping
    on dim.account_id = mapping.account_id::uuid
left join crm
    on mapping.crm_account_id = crm.crm_account_id
