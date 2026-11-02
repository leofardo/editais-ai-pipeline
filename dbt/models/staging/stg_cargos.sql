-- Cargos da extração escolhida em stg_editais (mesmo sha256 + versão + momento).
select
    concat(c.sha256, '-', cast(c.cargo_idx as string))   as cargo_id,
    c.sha256                                             as edital_id,
    c.cargo_idx,
    trim(c.nome)                                         as cargo,
    lower(coalesce(c.area, 'nao_informado'))             as area,
    c.escolaridade,
    c.vagas_total,
    c.vagas_ampla_concorrencia,
    coalesce(c.vagas_referem_se_ao_grupo, false)         as vagas_de_grupo,
    c.vagas_total_grupo,
    c.cadastro_reserva,
    cast(c.salario_inicial as float64)                   as salario_inicial,
    c.carga_horaria_semanal,
    c.localidade,
    c.requisitos,
    c.pagina_fonte,
    c.vagas_no_texto,
    c.salario_no_texto
from {{ source('silver', 'cargos') }} c
join {{ ref('stg_editais') }} e
  on  c.sha256 = e.edital_id
  and c.model = e.model
  and c.prompt_version = e.prompt_version
  and c.extracted_at = e.extracted_at
