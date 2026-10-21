-- Candidates: Watch slots whose cheapest current price passes the Deal test.
-- Walking skeleton: one-way only, and with no Baseline yet only a Price threshold can produce a
-- Candidate (ticket 04 adds composition, ticket 05 adds the Baseline test and tiers).
with observed as (
    select *
    from {{ ref('stg_leg_prices') }}
    where observed_at <= {{ as_of() }}
),

latest_per_source as (
    select
        *,
        row_number() over (
            partition by source, origin, destination, departure_date
            order by observed_at desc
        ) as recency
    from observed
),

cheapest as (
    select
        *,
        row_number() over (
            partition by origin, destination, departure_date
            order by price_per_adult_eur, source
        ) as price_rank
    from latest_per_source
    where recency = 1
),

priced_slots as (
    select
        s.watch_id,
        s.origin,
        s.destination,
        s.outbound_date,
        s.return_date,
        w.adults,
        w.price_threshold_eur,
        w.price_threshold_basis,
        c.price_per_adult_eur,
        c.price_per_adult_eur * w.adults as price_total_eur,
        c.source,
        c.observed_at
    from {{ source('app', 'watch_slots') }} as s
    inner join {{ source('app', 'watches') }} as w on w.id = s.watch_id
    inner join cheapest as c
        on c.origin = s.origin
        and c.destination = s.destination
        and c.departure_date = s.outbound_date
        and c.price_rank = 1
    where s.return_date is null
        and w.status = 'active'
)

select
    watch_id,
    origin,
    destination,
    outbound_date,
    return_date,
    adults,
    price_per_adult_eur,
    price_total_eur,
    source,
    observed_at,
    cast(null as {{ dbt.type_string() }}) as baseline_tier
from priced_slots
where price_threshold_eur is not null
    and case
        when price_threshold_basis = 'per_adult' then price_per_adult_eur
        else price_total_eur
    end < price_threshold_eur
