{# The owner's local (Helsinki) calendar date of a timestamp: Baseline observation days. #}
{% macro local_date(ts) -%}
    {{ return(adapter.dispatch('local_date', 'flight_scanner')(ts)) }}
{%- endmacro %}

{% macro default__local_date(ts) -%}
    to_date(from_utc_timestamp({{ ts }}, 'Europe/Helsinki'))
{%- endmacro %}

{% macro postgres__local_date(ts) -%}
    cast(({{ ts }}) at time zone 'Europe/Helsinki' as date)
{%- endmacro %}

{# Stay-night bucket of a trip: one_way, 1-2, 3-4, 5-7, 8-14, 15+ (0 nights counts as 1-2). #}
{% macro stay_bucket(outbound_date, return_date) -%}
    case
        when {{ return_date }} is null then 'one_way'
        when {{ dbt.datediff(outbound_date, return_date, 'day') }} <= 2 then '1-2'
        when {{ dbt.datediff(outbound_date, return_date, 'day') }} <= 4 then '3-4'
        when {{ dbt.datediff(outbound_date, return_date, 'day') }} <= 7 then '5-7'
        when {{ dbt.datediff(outbound_date, return_date, 'day') }} <= 14 then '8-14'
        else '15+'
    end
{%- endmacro %}

{# Departure month of a trip: the first day of the outbound date's month (a date). #}
{% macro departure_month(d) -%}
    cast({{ dbt.date_trunc('month', d) }} as date)
{%- endmacro %}
