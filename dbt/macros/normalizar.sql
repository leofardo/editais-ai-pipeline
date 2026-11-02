{#- Minúsculas e sem acento: "Educação" -> "educacao". Ajuda o Text-to-SQL a casar textos. -#}
{% macro normalizar(col) -%}
regexp_replace(normalize(lower({{ col }}), NFD), r'\p{M}', '')
{%- endmacro %}
