-- Candidates: Watch slots whose composed trip price (marts.trip_prices) passes the Deal test.
-- With no Baseline yet only a Price threshold can produce a Candidate (ticket 05 adds the
-- Baseline test and tiers).
with priced_slots as (
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
        p.price_per_adult_eur,
        p.price_per_adult_eur * w.adults as price_total_eur,
        p.source,
        p.observed_at,
        p.airlines,
        p.stops,
        p.travel_minutes
    from {{ ref('trip_prices') }} as p
    inner join {{ source('app', 'watches') }} as w on w.id = p.watch_id
    where w.status = 'active'
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
    cast(null as {{ dbt.type_string() }}) as baseline_tier,
    -- Alert details (ticket 06), from the composed price (ticket 04). Baselines (ticket 05)
    -- fill the rest; until then they are null and Alerts omit them.
    airlines,
    stops,
    travel_minutes,
    ticketing = 'separate_tickets' as separate_tickets,
    cast(null as {{ dbt.type_string() }}) as booking_url,
    cast(null as {{ dbt.type_numeric() }}) as baseline_per_adult_eur
from priced_slots
where price_threshold_eur is not null
    and case
        when price_threshold_basis = 'per_adult' then price_per_adult_eur
        else price_total_eur
    end < price_threshold_eur
