-- Daily-minimum trip prices: what Baselines are computed from. One row per trip (origin,
-- destination, outbound, return) and observation day (Helsinki date) in the trailing Baseline
-- window up to and including today, with the trip's Baseline key.
--   One-way trips: the day's cheapest Leg price.
--   Round trips: the day's cheaper of the cheapest single-ticket Round-trip price and the sum of
--   the day's cheapest outbound and return Leg prices (ADR-0001), across sources.
-- Only (origin city, destination country) pairs some current Watch slot needs are built, which
-- bounds the Leg-pair composition to the routes that are watched.
with airports as (
    select code, coalesce(city, code) as city, country
    from {{ source('ref', 'airports') }}
),

as_of_day as (
    select {{ local_date(as_of()) }} as today
),

wanted as (
    select distinct oa.city as origin_city, da.country as destination_country
    from {{ source('app', 'watch_slots') }} as s
    inner join airports as oa on oa.code = s.origin
    inner join airports as da on da.code = s.destination
),

legs as (
    select
        l.origin,
        l.destination,
        l.departure_date,
        {{ local_date('l.observed_at') }} as obs_day,
        min(l.price_per_adult_eur) as price_per_adult_eur
    from {{ ref('stg_leg_prices') }} as l
    cross join as_of_day as t
    where l.observed_at <= {{ as_of() }}
        and {{ local_date('l.observed_at') }}
            > {{ dbt.dateadd('day', -var('baseline_window_days'), 't.today') }}
    group by l.origin, l.destination, l.departure_date, {{ local_date('l.observed_at') }}
),

round_trips as (
    select
        r.origin,
        r.destination,
        r.departure_date,
        r.return_date,
        {{ local_date('r.observed_at') }} as obs_day,
        min(r.price_per_adult_eur) as price_per_adult_eur
    from {{ ref('stg_round_trip_prices') }} as r
    cross join as_of_day as t
    where r.observed_at <= {{ as_of() }}
        and {{ local_date('r.observed_at') }}
            > {{ dbt.dateadd('day', -var('baseline_window_days'), 't.today') }}
    group by
        r.origin, r.destination, r.departure_date, r.return_date, {{ local_date('r.observed_at') }}
),

-- outbound Legs (and single tickets) of wanted routes, with their key's city and country
wanted_legs as (
    select l.*, oa.city as origin_city, da.country as destination_country
    from legs as l
    inner join airports as oa on oa.code = l.origin
    inner join airports as da on da.code = l.destination
    inner join wanted as w
        on w.origin_city = oa.city and w.destination_country = da.country
),

wanted_round_trips as (
    select r.*, oa.city as origin_city, da.country as destination_country
    from round_trips as r
    inner join airports as oa on oa.code = r.origin
    inner join airports as da on da.code = r.destination
    inner join wanted as w
        on w.origin_city = oa.city and w.destination_country = da.country
),

one_way as (
    select
        origin, destination, departure_date as outbound_date,
        cast(null as date) as return_date, obs_day, price_per_adult_eur,
        origin_city, destination_country
    from wanted_legs
),

round_trip_options as (
    select
        o.origin, o.destination, o.departure_date as outbound_date,
        r.departure_date as return_date, o.obs_day,
        o.price_per_adult_eur + r.price_per_adult_eur as price_per_adult_eur,
        o.origin_city, o.destination_country
    from wanted_legs as o
    inner join legs as r
        on r.origin = o.destination
        and r.destination = o.origin
        and r.obs_day = o.obs_day
        and r.departure_date >= o.departure_date
    union all
    select
        origin, destination, departure_date as outbound_date, return_date, obs_day,
        price_per_adult_eur, origin_city, destination_country
    from wanted_round_trips
),

round_trip as (
    select
        origin, destination, outbound_date, return_date, obs_day,
        min(price_per_adult_eur) as price_per_adult_eur,
        origin_city, destination_country
    from round_trip_options
    group by
        origin, destination, outbound_date, return_date, obs_day,
        origin_city, destination_country
),

trips as (
    select * from one_way
    union all
    select * from round_trip
)

select
    origin,
    destination,
    outbound_date,
    return_date,
    obs_day,
    price_per_adult_eur,
    origin_city,
    destination_country,
    {{ departure_month('outbound_date') }} as departure_month,
    {{ stay_bucket('outbound_date', 'return_date') }} as stay_bucket
from trips
