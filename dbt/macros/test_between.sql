{#- Teste genérico: valores fora de [min_value, max_value] falham (nulos são ignorados). -#}
{% test between(model, column_name, min_value, max_value) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and ({{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }})
{% endtest %}
