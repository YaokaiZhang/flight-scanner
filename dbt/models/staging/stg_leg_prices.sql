-- Leg prices normalised to EUR per adult (fx_rates seed). One row per Fare observation: the
-- cheapest row per payload, observation instant, route and departure date (a Price insight's
-- history points share one payload but each has its own instant). Currencies without a rate are
-- dropped.
with landed as (
    select
        l.*,
        fx.eur_per_unit,
        row_number() over (
            partition by
                l.payload_id, l.source, l.observed_at, l.origin, l.destination, l.departure_date
            order by l.price * fx.eur_per_unit / l.adults, l.airline
        ) as price_rank
    from {{ source('landing', 'leg_prices') }} as l
    inner join {{ ref('fx_rates') }} as fx on fx.currency = upper(l.currency)
)

select
    payload_id,
    source,
    observed_at,
    origin,
    destination,
    departure_date,
    cast(price * eur_per_unit / adults as numeric(10, 2)) as price_per_adult_eur,
    airline,
    stops,
    duration_min
from landed
where price_rank = 1
