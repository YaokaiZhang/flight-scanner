{#
  Change-only price history over a staging model of Fare observations.

  One row per (key, run of identical consecutive prices): a new row starts only when the price
  per adult differs from the previous observation of the same key, so repeated identical
  observations do not add rows. `valid_from` is the first observation of the run, `valid_to` the
  first observation of the next run (null while current), `last_observed_at` the last time the
  run's price was seen. Pure SQL over staging, so it is rebuilt from raw payloads alone.
#}
{% macro change_only_history(relation, keys) -%}
{%- set k = keys | join(', ') -%}
with observed as (
    select
        {{ k }},
        observed_at,
        payload_id,
        price_per_adult_eur,
        airline,
        stops,
        duration_min,
        row_number() over (
            partition by {{ k }}, observed_at
            order by price_per_adult_eur, payload_id
        ) as same_instant_rank
    from {{ relation }}
    where observed_at <= {{ as_of() }}
),

sequenced as (
    select
        *,
        lag(price_per_adult_eur) over (partition by {{ k }} order by observed_at) as previous_price
    from observed
    where same_instant_rank = 1
),

versioned as (
    select
        *,
        sum(
            case when previous_price is null or previous_price <> price_per_adult_eur then 1 else 0 end
        ) over (
            partition by {{ k }} order by observed_at rows between unbounded preceding and current row
        ) as version
    from sequenced
),

runs as (
    select
        {{ k }},
        version,
        min(observed_at) as valid_from,
        max(observed_at) as last_observed_at,
        count(*) as observations
    from versioned
    group by {{ k }}, version
),

firsts as (
    select
        *,
        row_number() over (partition by {{ k }}, version order by observed_at) as position_in_run
    from versioned
)

select
    {%- for c in keys %}
    r.{{ c }},
    {%- endfor %}
    r.valid_from,
    lead(r.valid_from) over (partition by {% for c in keys %}r.{{ c }}{{ ", " if not loop.last }}{% endfor %} order by r.valid_from) as valid_to,
    r.last_observed_at,
    r.observations,
    f.price_per_adult_eur,
    f.airline,
    f.stops,
    f.duration_min,
    f.payload_id as first_payload_id
from runs as r
inner join firsts as f
    on {% for c in keys %}f.{{ c }} = r.{{ c }} and {% endfor %}f.version = r.version
    and f.position_in_run = 1
{%- endmacro %}
