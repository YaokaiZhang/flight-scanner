-- Candidates: Watch slots whose composed trip price (marts.trip_prices) passes the Deal test.
-- The trip is judged against the first Baseline tier its key has: route, then destination
-- country, then provisional (low confidence; Verification re-judges it, ticket 08).
--   Route or country Baseline: price per adult at least the Watch's sensitivity below it, and
--   under the Price threshold if the Watch has one.
--   Provisional Baseline only: the Price threshold decides when the Watch has one (a low-
--   confidence estimate never vetoes it); otherwise the sensitivity test against it does.
--   No Baseline at all: only a Price threshold can make a Candidate.
-- Each Candidate carries the Baseline version (tier, method, computed_at, support) it was judged
-- against; record_deals copies these columns into app.deals as they are.
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

versions as (
    select
        tier, origin_city, destination, departure_month, stay_bucket,
        max(computed_at) as version_computed_at
    from {{ ref('baseline_versions') }}
    group by tier, origin_city, destination, departure_month, stay_bucket
),

baselines as (
    select b.*, v.version_computed_at
    from {{ ref('baselines') }} as b
    inner join versions as v
        on v.tier = b.tier
        and v.origin_city = b.origin_city
        and v.destination = b.destination
        and v.departure_month = b.departure_month
        and v.stay_bucket = b.stay_bucket
),

judged as (
    select
        s.*,
        b.tier as baseline_tier,
        b.median_per_adult_eur as baseline_per_adult_eur,
        b.method as baseline_method,
        b.version_computed_at as baseline_computed_at,
        b.observations as baseline_observations,
        b.observation_days as baseline_observation_days,
        row_number() over (
            partition by s.watch_id, s.origin, s.destination, s.outbound_date, s.return_date
            order by case b.tier when 'route' then 1 when 'country' then 2 else 3 end
        ) as tier_rank
    from priced_slots as s
    left join baselines as b
        on b.origin_city = s.origin_city
        and b.departure_month = s.departure_month
        and b.stay_bucket = s.stay_bucket
        and (
            (b.tier in ('route', 'provisional') and b.destination = s.destination)
            or (b.tier = 'country' and b.destination = s.destination_country)
        )
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
    when baseline_tier in ('route', 'country')
        then below_baseline and (price_threshold_eur is null or under_threshold)
    -- a low-confidence provisional Baseline never vetoes a Price threshold
    when baseline_tier = 'provisional' and price_threshold_eur is null then below_baseline
    else under_threshold
end
