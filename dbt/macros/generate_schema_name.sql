{# Use the custom schema name as-is (staging, marts) instead of <target>_<custom>.
   On Databricks (ADR-0003) the same models land in the medallion schemas instead: what verda
   keeps in staging/history is silver there (loaded from the daily export), marts are gold. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set schema = custom_schema_name if custom_schema_name is not none else target.schema -%}
    {%- if target.type == 'databricks' -%}
        {{ 'gold' if schema == 'marts' else 'silver' }}
    {%- else -%}
        {{ schema }}
    {%- endif -%}
{%- endmacro %}
