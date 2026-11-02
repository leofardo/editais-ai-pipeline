-- Vagas e salário por área e escolaridade. Só conta vagas específicas do cargo (não de grupo).
select
    area,
    escolaridade,
    count(*)                                   as qtd_cargos,
    count(distinct edital_id)                  as qtd_editais,
    sum(vagas_total)                           as vagas_especificas,
    countif(vagas_de_grupo)                    as cargos_com_vagas_de_grupo,
    round(avg(salario_inicial), 2)             as salario_medio,
    min(salario_inicial)                       as salario_min,
    max(salario_inicial)                       as salario_max
from {{ ref('fct_cargos') }}
group by 1, 2
