-- Pega o erro real do edital SEE-MG: o mesmo número grande de vagas repetido em vários cargos
-- do mesmo edital costuma ser um total de carreira copiado em cada especialidade.
-- Falha se >= 3 cargos de um edital têm o mesmo vagas_total >= 50 (sem estarem marcados como grupo).
select
    edital_id,
    vagas_total,
    count(*) as cargos_com_mesmo_numero,
    string_agg(cargo, ' | ' limit 5) as exemplos
from {{ ref('fct_cargos') }}
where vagas_total >= 50
  and not vagas_de_grupo
group by 1, 2
having count(*) >= 3
