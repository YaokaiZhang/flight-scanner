-- Every Baseline version ever computed (append-only): a current Baseline is appended when its
-- tier and key are new or its method, value, spread or support changed since the latest stored
-- version. A version is identified by (tier, key, computed_at); Deals record its computed_at.
{{ config(materialized='incremental') }}

with current_baselines as (
    select * from {{ ref('baselines') }}
)

{% if is_incremental() %}
, stored as (
    select
        v.*,
        row_number() over (
            partition by tier, origin_city, destination, departure_month, stay_bucket
            order by computed_at desc
        ) as recency
    from {{ this }} as v
)
{% endif %}

select
    b.tier,
    b.origin_city,
    b.destination,
    b.departure_month,
    b.stay_bucket,
    b.method,
    b.median_per_adult_eur,
    b.mad_eur,
    b.observations,
    b.observation_days,
    b.computed_at
from current_baselines as b
{% if is_incremental() %}
left join stored as s
    on s.recency = 1
    and s.tier = b.tier
    and s.origin_city = b.origin_city
    and s.destination = b.destination
    and s.departure_month = b.departure_month
    and s.stay_bucket = b.stay_bucket
where s.tier is null
    or s.method <> b.method
    or s.median_per_adult_eur <> b.median_per_adult_eur
    or s.mad_eur <> b.mad_eur
    or s.observations <> b.observations
    or s.observation_days <> b.observation_days
{% endif %}
