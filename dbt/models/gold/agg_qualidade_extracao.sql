-- Painel de qualidade da extração (LLM): acurácia por versão de prompt e campo, a partir dos gabaritos.
select
    model,
    prompt_version,
    campo,
    count(*)                                         as avaliacoes,
    countif(status = 'ok')                           as acertos,
    countif(status = 'alucinacao')                   as alucinacoes,
    countif(status = 'omissao')                      as omissoes,
    round(safe_divide(countif(status = 'ok'), count(*)), 3) as acuracia,
    max(evaluated_at)                                as ultima_avaliacao
from {{ source('silver', 'extraction_eval') }}
where campo != 'encontrado'
group by 1, 2, 3
