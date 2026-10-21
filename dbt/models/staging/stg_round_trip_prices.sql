-- Round-trip prices normalised to EUR per adult. One row per observation.
select
    payload_id,
    source,
    observed_at,
    origin,
    destination,
    departure_date,
    return_date,
    cast(price as numeric(10, 2)) / adults as price_per_adult_eur,
    airline,
    stops,
    duration_min
from {{ source('landing', 'round_trip_prices') }}
where currency = 'EUR'
