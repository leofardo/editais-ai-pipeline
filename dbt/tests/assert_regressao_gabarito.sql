-- A versão de prompt usada na gold não pode ter acurácia < 95% nos gabaritos (se foi avaliada).
{{ config(severity='error') }}
select q.prompt_version, sum(q.acertos) as acertos, sum(q.avaliacoes) as avaliacoes
from {{ ref('agg_qualidade_extracao') }} q
where q.prompt_version in (select distinct prompt_version from {{ ref('dim_editais') }})
group by 1
having safe_divide(sum(q.acertos), sum(q.avaliacoes)) < 0.95
