{#- staging -> editais_gold_staging ; gold -> editais_gold -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.dataset }}{%- else -%}{{ target.dataset }}_{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
