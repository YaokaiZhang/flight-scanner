-- Trip composition (ADR-0001): the current cheapest price of every Watch slot.
-- One-way slots use the outbound Leg price. Round-trip slots pair the outbound Leg price
-- (origin -> destination on the outbound date) with the return Leg price (destination -> origin
-- on the return date), compare the pair with any single-ticket Round-trip price for the same
-- airports and dates, and keep the cheaper (a tie goes to the single ticket).
-- Only Leg prices for the exact airport pair are used, so no Self-transfer within one direction
-- is ever composed. Each source's latest observation at or before as_of counts; the cheapest
-- source wins. Airlines, stops and travel time (for Alerts) come from the chosen price(s).
-- Verification sources (live checks, ticket 08) are not current prices: they only feed Baselines.
-- Data-quality gates (ticket 10): prices of a gated slice (source and Leg / Round-trip origin, or
-- the whole source) are left out, so they never make a Candidate; other sources still price the
-- trip.
with gates as (
    select source, origin
    from {{ source('app', 'quality_gates') }}
),

legs as (
    select *
    from {{ ref('stg_leg_prices') }} as l
    where observed_at <= {{ as_of() }}
        and {{ not_verification_source('source') }}
        and not exists (
            select 1 from gates as g
            where g.source = l.source and (g.origin is null or g.origin = l.origin)
        )
),

legs_latest as (
    select
        *,
        row_number() over (
            partition by source, origin, destination, departure_date
            order by observed_at desc
        ) as recency
    from legs
),

leg_best as (
    select
        *,
        row_number() over (
            partition by origin, destination, departure_date
            order by price_per_adult_eur, source
        ) as price_rank
    from legs_latest
    where recency = 1
),

round_trips as (
    select *
    from {{ ref('stg_round_trip_prices') }} as t
    where observed_at <= {{ as_of() }}
        and {{ not_verification_source('source') }}
        and not exists (
            select 1 from gates as g
            where g.source = t.source and (g.origin is null or g.origin = t.origin)
        )
),

round_trips_latest as (
    select
        *,
        row_number() over (
            partition by source, origin, destination, departure_date, return_date
            order by observed_at desc
        ) as recency
    from round_trips
),

round_trip_best as (
    select
        *,
        row_number() over (
            partition by origin, destination, departure_date, return_date
            order by price_per_adult_eur, source
        ) as price_rank
    from round_trips_latest
    where recency = 1
),

slots as (
    select s.watch_id, s.origin, s.destination, s.outbound_date, s.return_date
    from {{ source('app', 'watch_slots') }} as s
),

one_way as (
    select
        s.watch_id,
        s.origin,
        s.destination,
        s.outbound_date,
        s.return_date,
        'one_way' as ticketing,
        o.price_per_adult_eur,
        o.source,
        o.observed_at,
        o.airline as airlines,
        o.stops,
        o.duration_min as travel_minutes
    from slots as s
    inner join leg_best as o
        on o.origin = s.origin
        and o.destination = s.destination
        and o.departure_date = s.outbound_date
        and o.price_rank = 1
    where s.return_date is null
),

separate_tickets as (
    select
        s.watch_id,
        s.origin,
        s.destination,
        s.outbound_date,
        s.return_date,
        'separate_tickets' as ticketing,
        o.price_per_adult_eur + r.price_per_adult_eur as price_per_adult_eur,
        case
            when o.source = r.source then o.source
            else {{ dbt.concat(['o.source', "'+'", 'r.source']) }}
        end as source,
        case
            when o.observed_at < r.observed_at then o.observed_at
            else r.observed_at
        end as observed_at,
        case
            when o.airline is null then r.airline
            when r.airline is null or r.airline = o.airline then o.airline
            else {{ dbt.concat(['o.airline', "', '", 'r.airline']) }}
        end as airlines,
        greatest(o.stops, r.stops) as stops,
        o.duration_min + r.duration_min as travel_minutes
    from slots as s
    inner join leg_best as o
        on o.origin = s.origin
        and o.destination = s.destination
        and o.departure_date = s.outbound_date
        and o.price_rank = 1
    inner join leg_best as r
        on r.origin = s.destination
        and r.destination = s.origin
        and r.departure_date = s.return_date
        and r.price_rank = 1
    where s.return_date is not null
),

single_ticket as (
    select
        s.watch_id,
        s.origin,
        s.destination,
        s.outbound_date,
        s.return_date,
        'single_ticket' as ticketing,
        t.price_per_adult_eur,
        t.source,
        t.observed_at,
        t.airline as airlines,
        t.stops,
        t.duration_min as travel_minutes
    from slots as s
    inner join round_trip_best as t
        on t.origin = s.origin
        and t.destination = s.destination
        and t.departure_date = s.outbound_date
        and t.return_date = s.return_date
        and t.price_rank = 1
    where s.return_date is not null
),

options as (
    select * from one_way
    union all
    select * from separate_tickets
    union all
    select * from single_ticket
),

ranked as (
    select
        *,
        row_number() over (
            partition by watch_id, origin, destination, outbound_date, return_date
            order by
                price_per_adult_eur,
                case ticketing when 'single_ticket' then 0 else 1 end
        ) as option_rank
    from options
)

select
    watch_id,
    origin,
    destination,
    outbound_date,
    return_date,
    ticketing,
    price_per_adult_eur,
    source,
    observed_at,
    airlines,  -- comma-separated when the two Leg tickets differ
    stops,  -- most stops in any one direction
    travel_minutes  -- all legs together
from ranked
where option_rank = 1
