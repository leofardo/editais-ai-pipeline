-- Uma linha por edital, com métricas agregadas dos cargos.
-- Vagas de grupo (ex.: 10.170 da carreira de Professor) entram UMA vez por grupo, não por especialidade.
with vagas_cargo as (
    select edital_id, sum(vagas_total) as vagas_cargos
    from {{ ref('stg_cargos') }}
    where not vagas_de_grupo
    group by 1
),

vagas_grupo as (
    select edital_id, sum(vagas_total_grupo) as vagas_grupos
    from (select distinct edital_id, vagas_total_grupo from {{ ref('stg_cargos') }} where vagas_de_grupo)
    group by 1
),

cargos as (
    select
        edital_id,
        count(*)                as qtd_cargos,
        min(salario_inicial)    as salario_min,
        max(salario_inicial)    as salario_max,
        countif(not coalesce(vagas_no_texto, true) or not coalesce(salario_no_texto, true)) as cargos_nao_ancorados
    from {{ ref('stg_cargos') }}
    group by 1
)

select
    e.edital_id,
    e.orgao,
    {{ normalizar('e.orgao') }}                                 as orgao_norm,
    e.numero_edital,
    e.banca_organizadora,
    e.esfera,
    e.uf,
    e.municipio,
    e.data_publicacao,
    e.inscricao_inicio,
    e.inscricao_fim,
    e.data_prova,
    case
        when e.inscricao_inicio is null or e.inscricao_fim is null then 'sem_data'
        when current_date() < e.inscricao_inicio then 'em_breve'
        when current_date() <= e.inscricao_fim  then 'aberta'
        else 'encerrada'
    end                                                         as status_inscricao,
    e.taxa_inscricao_min,
    e.taxa_inscricao_max,
    coalesce(c.qtd_cargos, 0)                                   as qtd_cargos,
    nullif(coalesce(vc.vagas_cargos, 0) + coalesce(vg.vagas_grupos, 0), 0) as vagas_total,
    c.salario_min,
    c.salario_max,
    coalesce(c.cargos_nao_ancorados, 0)                         as cargos_nao_ancorados,
    e.documento_completo,
    e.original_filename,
    e.model,
    e.prompt_version,
    e.input_tokens,
    e.output_tokens
from {{ ref('stg_editais') }} e
left join cargos c       using (edital_id)
left join vagas_cargo vc using (edital_id)
left join vagas_grupo vg using (edital_id)
