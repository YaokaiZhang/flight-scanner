-- Candidates: Watch slots whose composed trip price (marts.trip_prices) passes the Deal test.
-- The trip is judged against the first Baseline tier it has: route, then destination country,
-- then the trip's Price insight (from an earlier Verification, ticket 08), then provisional (low
-- confidence; Verification re-judges it against the Price insight).
--   Route, country or Price-insight Baseline: price per adult at least the Watch's sensitivity
--   below it, and under the Price threshold if the Watch has one.
--   Provisional Baseline only: the Price threshold decides when the Watch has one (a low-
--   confidence estimate never vetoes it); otherwise the sensitivity test against it does.
--   No Baseline at all: only a Price threshold can make a Candidate.
-- Each Candidate carries the Baseline version (tier, method, computed_at, support) it was judged
-- against; record_deals copies these columns into app.deals as they are. Verification
-- (flight_scanner.verification) repeats this test on the live price.
with airports as (
    select code, coalesce(city, code) as city, country
    from {{ source('ref', 'airports') }}
),

priced_slots as (
    select
        p.watch_id,
        p.origin,
        p.destination,
        p.outbound_date,
        p.return_date,
        p.ticketing,
        w.adults,
        w.price_threshold_eur,
        w.price_threshold_basis,
        w.sensitivity_pct,
        p.price_per_adult_eur,
        p.price_per_adult_eur * w.adults as price_total_eur,
        p.source,
        p.observed_at,
        p.airlines,
        p.stops,
        p.travel_minutes,
        coalesce(oa.city, p.origin) as origin_city,
        da.country as destination_country,
        {{ departure_month('p.outbound_date') }} as departure_month,
        {{ stay_bucket('p.outbound_date', 'p.return_date') }} as stay_bucket
    from {{ ref('trip_prices') }} as p
    inner join {{ source('app', 'watches') }} as w on w.id = p.watch_id
    left join airports as oa on oa.code = p.origin
    left join airports as da on da.code = p.destination
    where w.status = 'active'
),

-- route/country/provisional Baselines: published by the lakehouse while fresh, else the
-- operational recompute (ticket 12); computed_at is the version
baselines as (
    select * from {{ ref('effective_baselines') }}
),

tiers as (
    select
        s.watch_id, s.origin, s.destination, s.outbound_date, s.return_date,
        b.tier, b.median_per_adult_eur, b.method, b.computed_at,
        b.observations, b.observation_days
    from priced_slots as s
    inner join baselines as b
        on b.origin_city = s.origin_city
        and b.departure_month = s.departure_month
        and b.stay_bucket = s.stay_bucket
        and (
            (b.tier in ('route', 'provisional') and b.destination = s.destination)
            or (b.tier = 'country' and b.destination = s.destination_country)
        )
    union all
    select
        s.watch_id, s.origin, s.destination, s.outbound_date, s.return_date,
        i.tier, i.median_per_adult_eur, i.method, i.computed_at,
        i.observations, i.observation_days
    from priced_slots as s
    inner join {{ ref('price_insights') }} as i
        on i.origin = s.origin
        and i.destination = s.destination
        and i.outbound_date = s.outbound_date
        and (i.return_date = s.return_date or (i.return_date is null and s.return_date is null))
),

judged as (
    select
        s.*,
        b.tier as baseline_tier,
        b.median_per_adult_eur as baseline_per_adult_eur,
        b.method as baseline_method,
        b.computed_at as baseline_computed_at,
        b.observations as baseline_observations,
        b.observation_days as baseline_observation_days,
        row_number() over (
            partition by s.watch_id, s.origin, s.destination, s.outbound_date, s.return_date
            order by case b.tier
                when 'route' then 1
                when 'country' then 2
                when 'price_insight' then 3
                else 4
            end
        ) as tier_rank
    from priced_slots as s
    left join tiers as b
        on b.watch_id = s.watch_id
        and b.origin = s.origin
        and b.destination = s.destination
        and b.outbound_date = s.outbound_date
        and (b.return_date = s.return_date or (b.return_date is null and s.return_date is null))
),

tested as (
    select
        *,
        price_threshold_eur is not null
        and case
            when price_threshold_basis = 'per_adult' then price_per_adult_eur
            else price_total_eur
        end < price_threshold_eur as under_threshold,
        price_per_adult_eur
        <= baseline_per_adult_eur * (100 - sensitivity_pct) / 100.0 as below_baseline
    from judged
    where tier_rank = 1
)

select
    watch_id,
    origin,
    destination,
    outbound_date,
    return_date,
    ticketing,
    adults,
    price_per_adult_eur,
    price_total_eur,
    source,
    observed_at,
    baseline_tier,
    -- Alert details (ticket 06), from the composed price (ticket 04) and the Baseline.
    airlines,
    stops,
    travel_minutes,
    ticketing = 'separate_tickets' as separate_tickets,
    cast(null as {{ dbt.type_string() }}) as booking_url,
    baseline_per_adult_eur,
    baseline_method,
    baseline_computed_at,
    baseline_observations,
    baseline_observation_days
from tested
where case
    when baseline_tier in ('route', 'country', 'price_insight')
        then below_baseline and (price_threshold_eur is null or under_threshold)
    -- a low-confidence provisional Baseline never vetoes a Price threshold
    when baseline_tier = 'provisional' and price_threshold_eur is null then below_baseline
    else under_threshold
end
