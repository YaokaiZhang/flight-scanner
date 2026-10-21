{# The pipeline's clock instant as a timestamp literal. Never use now()/current_timestamp.
   The pipeline sets env var FS_AS_OF; by hand, `--vars '{as_of: ...}'` works too. Both are read
   only at execution: anything the parse depends on (vars, env vars read while parsing) would make
   dbt re-parse the project on every scan. #}
{% macro as_of() -%}
    {%- set value = '1970-01-01T00:00:00+00:00' -%}  {# parse time only #}
    {%- if execute -%}
        {%- set value = var('as_of') or env_var('FS_AS_OF', '') -%}
        {%- if not value -%}
            {{ exceptions.raise_compiler_error("the injected clock is required: env FS_AS_OF or var 'as_of'") }}
        {%- endif -%}
    {%- endif -%}
    {{ return(adapter.dispatch('as_of', 'flight_scanner')(value)) }}
{%- endmacro %}

{% macro default__as_of(value) -%}
    cast('{{ value }}' as timestamp)
{%- endmacro %}

{% macro postgres__as_of(value) -%}
    cast('{{ value }}' as timestamp with time zone)
{%- endmacro %}
