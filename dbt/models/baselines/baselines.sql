-- Current Baselines: the normal per-adult price of comparable trips, per tier and key
-- (origin city, destination, departure month, Stay-night bucket), computed at as_of.
--   route:       destination = airport. Median of the daily-minimum trip prices of completed
--                observation days in the trailing window (today is excluded, so a fare seen
--                today never moves its own Baseline), MAD as spread. Needs >= baseline_min_
--                observations points over >= baseline_min_days distinct days.
--   country:     the same over every destination airport in the country (destination = country).
--   provisional: low confidence. Cross-sectional median of each trip's most recent daily-minimum
--                price across the key's departure dates still ahead; needs >= provisional_min_trips.
-- Keys without enough support have no row for that tier. Versions: baseline_versions.
with obs as (
    select * from {{ ref('baseline_observations') }}
),

as_of_day as (
    select {{ local_date(as_of()) }} as today
),

latest_per_trip as (
    select
        o.*,
        row_number() over (
            partition by origin, destination, outbound_date, return_date
            order by obs_day desc
        ) as recency
    from obs as o
),

points as (
    select
        'route' as tier, o.origin_city, o.destination, o.departure_month, o.stay_bucket,
        o.obs_day, o.price_per_adult_eur
    from obs as o
    cross join as_of_day as t
    where o.obs_day < t.today
    union all
    select
        'country' as tier, o.origin_city, o.destination_country as destination,
        o.departure_month, o.stay_bucket, o.obs_day, o.price_per_adult_eur
    from obs as o
    cross join as_of_day as t
    where o.obs_day < t.today
    union all
    select
        'provisional' as tier, p.origin_city, p.destination, p.departure_month, p.stay_bucket,
        p.obs_day, p.price_per_adult_eur
    from latest_per_trip as p
    cross join as_of_day as t
    where p.recency = 1 and p.outbound_date >= t.today
),

stats as (
    select
        tier, origin_city, destination, departure_month, stay_bucket,
        percentile_cont(0.5) within group (order by price_per_adult_eur) as median_price,
        count(*) as observations,
        count(distinct obs_day) as observation_days
    from points
    group by tier, origin_city, destination, departure_month, stay_bucket
),

supported as (
    select *
    from stats
    where (
        tier in ('route', 'country')
        and observations >= {{ var('baseline_min_observations') }}
        and observation_days >= {{ var('baseline_min_days') }}
    ) or (
        tier = 'provisional' and observations >= {{ var('provisional_min_trips') }}
    )
),

spread as (
    select
        s.tier, s.origin_city, s.destination, s.departure_month, s.stay_bucket,
        percentile_cont(0.5) within group (
            order by abs(p.price_per_adult_eur - s.median_price)
        ) as mad
    from supported as s
    inner join points as p
        on p.tier = s.tier
        and p.origin_city = s.origin_city
        and p.destination = s.destination
        and p.departure_month = s.departure_month
        and p.stay_bucket = s.stay_bucket
    group by s.tier, s.origin_city, s.destination, s.departure_month, s.stay_bucket
)

select
    s.tier,
    s.origin_city,
    s.destination,
    s.departure_month,
    s.stay_bucket,
    case
        when s.tier = 'provisional' then 'cross_sectional_median'
        else 'daily_min_median_{{ var("baseline_window_days") }}d'
    end as method,
    cast(s.median_price as numeric(10, 2)) as median_per_adult_eur,
    cast(m.mad as numeric(10, 2)) as mad_eur,
    s.observations,
    s.observation_days,
    {{ as_of() }} as computed_at
from supported as s
inner join spread as m
    on m.tier = s.tier
    and m.origin_city = s.origin_city
    and m.destination = s.destination
    and m.departure_month = s.departure_month
    and m.stay_bucket = s.stay_bucket
