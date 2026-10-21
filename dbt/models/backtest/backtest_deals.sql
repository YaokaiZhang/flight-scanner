-- Backtest: was each past Deal a real dip? Judged from what the same trip (origin, destination,
-- outbound, return) cost on the Helsinki days after the Deal was detected, up to as_of.
--   Deal price: the per-adult price of its first Alert (the price the owner was told), or, when
--   it was never alerted, the price its current Alert round is due on.
--   Baseline: the Baseline the Deal records (app.deals; refreshed while it is a Candidate).
--   Later daily price: the day's cheapest Leg price (one way), or the cheaper of the day's
--   single-ticket Round-trip price and its outbound + return Leg prices (ADR-0001), any source.
-- Outcome:
--   real_dip      some later daily price climbed back at least backtest_recovery_share of the way
--                 from the Deal price to the Baseline
--   stayed_low    never did, over at least backtest_min_later_days later observation days
--                 (a Baseline error or a seasonal shift)
--   pending       not enough later days yet, and the trip has not departed
--   inconclusive  the trip departed before there were enough later days
--   unjudged      no Baseline below which to dip (threshold-only Deal, or price not below it)
with as_of_day as (
    select {{ local_date(as_of()) }} as today
),

first_alerts as (
    select deal_id, min(price_total_eur) as price_total_eur
    from {{ source('app', 'alerts') }}
    where alert_round = 1 and sent_at <= {{ as_of() }}
    group by deal_id
),

deals as (
    select
        d.id as deal_id,
        d.watch_id,
        d.origin,
        d.destination,
        d.outbound_date,
        d.return_date,
        d.detected_at,
        {{ local_date('d.detected_at') }} as detected_day,
        d.baseline_tier,
        d.baseline_per_adult_eur,
        cast(
            coalesce(a.price_total_eur, d.alert_price_total_eur) / d.adults as numeric(10, 2)
        ) as price_per_adult_eur
    from {{ source('app', 'deals') }} as d
    left join first_alerts as a on a.deal_id = d.id
    where d.detected_at <= {{ as_of() }}
),

legs as (
    select *, {{ local_date('observed_at') }} as obs_day
    from {{ ref('stg_leg_prices') }}
    where observed_at <= {{ as_of() }}
),

outbound_legs as (
    select d.deal_id, l.obs_day, min(l.price_per_adult_eur) as price_per_adult_eur
    from deals as d
    inner join legs as l
        on l.origin = d.origin
        and l.destination = d.destination
        and l.departure_date = d.outbound_date
        and l.obs_day > d.detected_day
    group by d.deal_id, l.obs_day
),

return_legs as (
    select d.deal_id, l.obs_day, min(l.price_per_adult_eur) as price_per_adult_eur
    from deals as d
    inner join legs as l
        on l.origin = d.destination
        and l.destination = d.origin
        and l.departure_date = d.return_date
        and l.obs_day > d.detected_day
    group by d.deal_id, l.obs_day
),

single_tickets as (
    select
        d.deal_id,
        {{ local_date('r.observed_at') }} as obs_day,
        min(r.price_per_adult_eur) as price_per_adult_eur
    from deals as d
    inner join {{ ref('stg_round_trip_prices') }} as r
        on r.origin = d.origin
        and r.destination = d.destination
        and r.departure_date = d.outbound_date
        and r.return_date = d.return_date
        and r.observed_at <= {{ as_of() }}
        and {{ local_date('r.observed_at') }} > d.detected_day
    group by d.deal_id, {{ local_date('r.observed_at') }}
),

options as (
    select o.deal_id, o.obs_day, o.price_per_adult_eur
    from outbound_legs as o
    inner join deals as d on d.deal_id = o.deal_id
    where d.return_date is null
    union all
    select o.deal_id, o.obs_day, o.price_per_adult_eur + r.price_per_adult_eur
    from outbound_legs as o
    inner join return_legs as r on r.deal_id = o.deal_id and r.obs_day = o.obs_day
    union all
    select deal_id, obs_day, price_per_adult_eur
    from single_tickets
),

daily as (
    select deal_id, obs_day, min(price_per_adult_eur) as price_per_adult_eur
    from options
    group by deal_id, obs_day
),

later as (
    select
        deal_id,
        count(*) as later_observation_days,
        max(price_per_adult_eur) as highest_later_price_per_adult_eur,
        max(obs_day) as last_observation_day
    from daily
    group by deal_id
),

judged as (
    select
        d.*,
        coalesce(l.later_observation_days, 0) as later_observation_days,
        l.highest_later_price_per_adult_eur,
        l.last_observation_day,
        d.baseline_per_adult_eur is not null
        and d.price_per_adult_eur < d.baseline_per_adult_eur as below_baseline,
        l.highest_later_price_per_adult_eur
        >= d.price_per_adult_eur
        + {{ var('backtest_recovery_share') }}
        * (d.baseline_per_adult_eur - d.price_per_adult_eur) as recovered
    from deals as d
    left join later as l on l.deal_id = d.deal_id
)

select
    j.deal_id,
    j.watch_id,
    j.origin,
    j.destination,
    j.outbound_date,
    j.return_date,
    j.detected_at,
    j.baseline_tier,
    j.price_per_adult_eur,
    j.baseline_per_adult_eur,
    case
        when j.below_baseline
            then cast(
                round(
                    100 * (j.baseline_per_adult_eur - j.price_per_adult_eur)
                    / j.baseline_per_adult_eur,
                    1
                ) as numeric(5, 1)
            )
    end as pct_below_baseline,
    j.later_observation_days,
    j.highest_later_price_per_adult_eur,
    j.last_observation_day,
    case
        when not j.below_baseline then 'unjudged'
        when j.recovered then 'real_dip'
        when j.later_observation_days >= {{ var('backtest_min_later_days') }} then 'stayed_low'
        when j.outbound_date < t.today then 'inconclusive'
        else 'pending'
    end as outcome,
    {{ as_of() }} as computed_at
from judged as j
cross join as_of_day as t
