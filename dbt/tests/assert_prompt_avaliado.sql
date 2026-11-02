-- Toda combinação de modelo e versão de prompt usada na gold precisa ter sido avaliada nos gabaritos.
-- Lê a staging para reprovar antes de construir dim_editais e fct_cargos.
{{ config(severity='error') }}
select distinct e.model, e.prompt_version
from {{ ref('stg_editais') }} e
left join {{ ref('agg_qualidade_extracao') }} q
    on q.model = e.model and q.prompt_version = e.prompt_version
where q.prompt_version is null
