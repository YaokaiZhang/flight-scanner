{# The pipeline's clock instant as a timestamp literal. Never use now()/current_timestamp. #}
{% macro as_of() -%}
    {%- set value = var('as_of') -%}
    {%- if value is none -%}
        {%- if execute -%}
            {{ exceptions.raise_compiler_error("var 'as_of' is required (the injected clock)") }}
        {%- endif -%}
        {%- set value = '1970-01-01T00:00:00+00:00' -%}  {# parse time only #}
    {%- endif -%}
    {{ return(adapter.dispatch('as_of', 'flight_scanner')(value)) }}
{%- endmacro %}

{% macro default__as_of(value) -%}
    cast('{{ value }}' as timestamp)
{%- endmacro %}

{% macro postgres__as_of(value) -%}
    cast('{{ value }}' as timestamp with time zone)
{%- endmacro %}
