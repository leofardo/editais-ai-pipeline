-- Uma linha por edital: a extração mais recente (opcionalmente filtrando a versão do prompt).
with ranked as (
    select
        *,
        row_number() over (partition by sha256 order by extracted_at desc) as rn
    from {{ source('silver', 'editais') }}
    {% if var('prompt_version') %}
    where prompt_version = '{{ var("prompt_version") }}'
    {% endif %}
)

select
    sha256                                   as edital_id,
    original_filename,
    trim(orgao)                              as orgao,
    numero_edital,
    trim(banca_organizadora)                 as banca_organizadora,
    esfera,
    upper(uf)                                as uf,
    municipio,
    data_publicacao,
    inscricao_inicio,
    inscricao_fim,
    data_prova,
    cast(taxa_inscricao_min as float64)      as taxa_inscricao_min,
    cast(taxa_inscricao_max as float64)      as taxa_inscricao_max,
    documento_completo,
    observacoes,
    model,
    prompt_version,
    input_tokens,
    output_tokens,
    extracted_at
from ranked
where rn = 1
