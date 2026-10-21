-- Price-insight Baselines (tier 3, between the country and the provisional Baseline): the latest
-- Price insight of each trip observed in the trailing Baseline window, as a Baseline value.
--   median = the middle of the typical price range, spread (mad_eur) = half its width.
--   A Price insight is per trip (origin, destination, outbound, return), not per Baseline key.
--   computed_at = when the insight was observed: each insight is its own immutable version.
--   observations / observation_days = the price-history points it came with (one per day).
with insights as (
    select
        i.*,
        row_number() over (
            partition by i.origin, i.destination, i.departure_date, i.return_date
            order by i.observed_at desc, i.payload_id desc
        ) as recency
    from {{ ref('stg_price_insights') }} as i
    where i.observed_at <= {{ as_of() }}
        and {{ local_date('i.observed_at') }}
            > {{ dbt.dateadd('day', -var('baseline_window_days'), local_date(as_of())) }}
)

select
    'price_insight' as tier,
    origin,
    destination,
    departure_date as outbound_date,
    return_date,
    'typical_price_range' as method,
    cast((typical_low_per_adult_eur + typical_high_per_adult_eur) / 2 as numeric(10, 2))
        as median_per_adult_eur,
    cast((typical_high_per_adult_eur - typical_low_per_adult_eur) / 2 as numeric(10, 2))
        as mad_eur,
    typical_low_per_adult_eur,
    typical_high_per_adult_eur,
    price_level,
    history_points as observations,
    history_points as observation_days,
    source,
    observed_at as computed_at
from insights
where recency = 1
