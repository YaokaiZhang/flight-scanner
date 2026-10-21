-- Round-trip prices normalised to EUR per adult (fx_rates seed). One row per Fare observation:
-- the cheapest row per payload, route and dates. Currencies without a rate are dropped.
with landed as (
    select
        r.*,
        fx.eur_per_unit,
        row_number() over (
            partition by r.payload_id, r.source, r.origin, r.destination, r.departure_date, r.return_date
            order by r.price * fx.eur_per_unit / r.adults, r.airline
        ) as price_rank
    from {{ source('landing', 'round_trip_prices') }} as r
    inner join {{ ref('fx_rates') }} as fx on fx.currency = upper(r.currency)
)

select
    payload_id,
    source,
    observed_at,
    origin,
    destination,
    departure_date,
    return_date,
    cast(price * eur_per_unit / adults as numeric(10, 2)) as price_per_adult_eur,
    airline,
    stops,
    duration_min
from landed
where price_rank = 1
