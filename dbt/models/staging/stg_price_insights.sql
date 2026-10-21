-- Price insights normalised to EUR per adult (fx_rates seed): a source's typical price range for
-- one trip (return_date null = one way), one row per payload and trip. Currencies without a rate
-- are dropped.
with landed as (
    select
        i.*,
        fx.eur_per_unit,
        row_number() over (
            partition by
                i.payload_id, i.source, i.origin, i.destination, i.departure_date, i.return_date
            order by i.typical_low
        ) as dup_rank
    from {{ source('landing', 'price_insights') }} as i
    inner join {{ ref('fx_rates') }} as fx on fx.currency = upper(i.currency)
)

select
    payload_id,
    source,
    observed_at,
    origin,
    destination,
    departure_date,
    return_date,
    cast(typical_low * eur_per_unit / adults as numeric(10, 2)) as typical_low_per_adult_eur,
    cast(typical_high * eur_per_unit / adults as numeric(10, 2)) as typical_high_per_adult_eur,
    cast(lowest_price * eur_per_unit / adults as numeric(10, 2)) as lowest_per_adult_eur,
    price_level,
    history_points
from landed
where dup_rank = 1
