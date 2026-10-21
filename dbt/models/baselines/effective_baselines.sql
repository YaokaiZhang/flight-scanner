-- The Baselines detection uses, per tier and key: the latest version the lakehouse (Databricks,
-- ADR-0003) published, while it is at most published_baseline_max_age_days old; otherwise the
-- operational recompute (marts.baselines, rebuilt on verda every scan). Databricks is never on
-- the alerting path: when it is unavailable or over quota, the last published versions keep
-- being used until they age out.
--   computed_at = the version: the published row's own, or the latest marts.baseline_versions
--   row of the operational Baseline. method says which (databricks/... when published).
with operational_versions as (
    select
        tier, origin_city, destination, departure_month, stay_bucket,
        max(computed_at) as computed_at
    from {{ ref('baseline_versions') }}
    group by tier, origin_city, destination, departure_month, stay_bucket
),

operational as (
    select
        b.tier, b.origin_city, b.destination, b.departure_month, b.stay_bucket, b.method,
        b.median_per_adult_eur, b.mad_eur, b.observations, b.observation_days,
        v.computed_at
    from {{ ref('baselines') }} as b
    inner join operational_versions as v
        on v.tier = b.tier
        and v.origin_city = b.origin_city
        and v.destination = b.destination
        and v.departure_month = b.departure_month
        and v.stay_bucket = b.stay_bucket
),

published_versions as (
    select
        p.*,
        row_number() over (
            partition by tier, origin_city, destination, departure_month, stay_bucket
            order by computed_at desc
        ) as recency
    from {{ source('analytics', 'baseline_versions') }} as p
    where p.computed_at <= {{ as_of() }}
        and p.computed_at
            > {{ dbt.dateadd('day', -var('published_baseline_max_age_days'), as_of()) }}
),

published as (
    select
        tier, origin_city, destination, departure_month, stay_bucket, method,
        median_per_adult_eur, mad_eur, observations, observation_days, computed_at
    from published_versions
    where recency = 1
)

select * from published
union all
select o.*
from operational as o
left join published as p
    on p.tier = o.tier
    and p.origin_city = o.origin_city
    and p.destination = o.destination
    and p.departure_month = o.departure_month
    and p.stay_bucket = o.stay_bucket
where p.tier is null
