-- Every existing sales row appears once in the research worklist. The
-- outreach gate is intentionally closed until a real CRM check exists.
select sales.account_id
from {{ ref('mart_sales_queue') }} sales
left join {{ ref('mart_rep_research_queue') }} research
    on sales.account_id = research.account_id
where research.account_id is null

union all

select account_id
from {{ ref('mart_rep_research_queue') }}
where outreach_ready
