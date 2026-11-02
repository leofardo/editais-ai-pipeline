-- Fato no grão de cargo, enriquecido com o edital. Base para análises e para o Text-to-SQL (Fase 4).
select
    c.cargo_id,
    c.edital_id,
    e.orgao,
    e.esfera,
    e.uf,
    e.banca_organizadora,
    c.cargo,
    {{ normalizar('c.cargo') }}                 as cargo_norm,
    {{ normalizar('e.orgao') }}                 as orgao_norm,
    c.area,
    c.escolaridade,
    c.vagas_total,
    c.vagas_de_grupo,
    c.vagas_total_grupo,
    c.cadastro_reserva,
    c.salario_inicial,
    case
        when c.salario_inicial is null then 'nao_informado'
        when c.salario_inicial < 3000  then '1. até 3 mil'
        when c.salario_inicial < 6000  then '2. 3 a 6 mil'
        when c.salario_inicial < 10000 then '3. 6 a 10 mil'
        else                                '4. acima de 10 mil'
    end                                         as faixa_salarial,
    c.carga_horaria_semanal,
    c.localidade,
    c.requisitos,
    e.inscricao_inicio,
    e.inscricao_fim,
    e.data_prova,
    -- qualidade: o número veio de fato do texto? (ancoragem feita na silver)
    coalesce(c.vagas_no_texto, true) and coalesce(c.salario_no_texto, true) as numeros_ancorados,
    c.pagina_fonte,
    e.original_filename,
    e.prompt_version
from {{ ref('stg_cargos') }} c
join {{ ref('stg_editais') }} e using (edital_id)
