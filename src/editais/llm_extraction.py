"""Extração estruturada com LLM (silver).

Controles de custo:
- Só as páginas relevantes vão para o modelo (page_selection), com teto de tokens.
- Cache no data lake por (sha256, modelo, versão do prompt): reprocessar a DAG
  não chama a API de novo. Trocar o prompt => nova PROMPT_VERSION => reextração.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone

from editais.extraction_schema import Edital
from editais.storage import Storage

# v1 -> v2: no TCE-SP a v1 extraiu vagas da tabela "por cidade" (3 e 1) em vez do
#           quadro geral (59 e 4). A v2 explica a diferença entre total e distribuição.
# v2 -> v3: na SEE-MG a v2 repetiu o total da CARREIRA (10.170 vagas de Professor) em
#           cada uma das 14 especialidades. A v3 proíbe replicar totais agregados.
# v3 -> v4: a v3 NÃO resolveu (o modelo reconheceu o total da carreira nas observações,
#           mas repetiu mesmo assim). A v4 pede uma CLASSIFICAÇÃO (vagas_referem_se_ao_grupo)
#           e a regra é aplicada no código: valor de grupo vai para vagas_total_grupo.
# v4 -> v5: a v4 corrigiu MG, mas REGREDIU no TCE-SP (somou 59 + 4 = 63 no cargo "pai").
#           A v5 proíbe somar linhas e define quando um número é do grupo.
# v5 -> v6: a v5 seguiu somando. Causa: a própria regra da v2 ("só some a distribuição se...")
#           incentivava somar. A v6 reescreve as regras de vagas sem nenhuma instrução de soma.
PROMPT_VERSION = "v6"

SYSTEM_PROMPT = """Você é um extrator de dados de editais de concurso público brasileiros.
Regras:
- Extraia SOMENTE o que está escrito no texto. Se uma informação não estiver no texto, use null.
- Nunca invente cargos, valores ou datas.
- salario_inicial: remuneração/vencimento inicial MENSAL em reais. Se houver só faixa, use o menor valor.
- Datas no formato YYYY-MM-DD. Se só houver período, use o primeiro e o último dia.
- vagas_total: copie o número da coluna de vagas da LINHA DO PRÓPRIO CARGO no quadro geral de cargos.
  Não faça contas: nunca some, subtraia ou combine números de linhas diferentes. Se o cargo tem linha própria,
  o número dele é o daquela linha, mesmo que outro cargo tenha nome parecido.
- Tabelas que distribuem vagas por cidade, região ou cota são detalhamento: ignore-as para vagas_total.
- Tabelas podem aparecer "achatadas", com uma célula por linha, na ordem: cargo, requisitos, carga horária,
  remuneração, vagas.
- Liste cada cargo uma única vez. Se o mesmo cargo tiver especialidades diferentes, liste cada especialidade como um cargo.
- vagas_referem_se_ao_grupo = true quando o texto atribui o número a vários cargos de uma vez
  ("X vagas para os cargos da carreira de ...", "X vagas para os cargos A, B e C"). Nesse caso coloque esse X em
  vagas_total de cada especialidade. Caso contrário, false.
- O texto vem dividido em páginas com o marcador '=== Página N ==='. Use N em pagina_fonte.
- O texto pode conter apenas parte do edital (páginas selecionadas)."""


def default_model() -> str:
    return os.getenv("OPENAI_EXTRACTION_MODEL", "gpt-4.1-mini")


def input_hash(pages: list[dict]) -> str:
    """Hash do que vai para o modelo: se a limpeza/seleção mudar, o cache invalida."""
    return hashlib.sha256(build_user_content(pages).encode("utf-8")).hexdigest()[:12]


def cache_key(sha256: str, model: str, pages: list[dict]) -> str:
    return f"silver/llm_extractions/{sha256}/{model}__{PROMPT_VERSION}__{input_hash(pages)}.json"


def build_user_content(pages: list[dict]) -> str:
    return "\n\n".join(f"=== Página {p['page_number']} ===\n{p['text_clean']}" for p in pages)


def _parse(client, **kwargs):
    # Compatível com versões novas (chat.completions.parse) e antigas (beta.*) do SDK
    if hasattr(client.chat.completions, "parse"):
        return client.chat.completions.parse(**kwargs)
    return client.beta.chat.completions.parse(**kwargs)


def call_llm(pages: list[dict], model: str) -> tuple[Edital, dict]:
    from openai import OpenAI

    client = OpenAI(max_retries=2, timeout=180)
    resp = _parse(
        client,
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_content(pages)},
        ],
        response_format=Edital,
    )
    msg = resp.choices[0].message
    if msg.refusal or msg.parsed is None:
        raise RuntimeError(f"Modelo não retornou extração válida: {msg.refusal!r}")
    usage = {"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens}
    return msg.parsed, usage


def extract_with_cache(sha256: str, pages: list[dict], storage: Storage, model: str | None = None) -> dict:
    """Retorna o payload da extração (do cache ou chamando o LLM)."""
    model = model or default_model()
    key = cache_key(sha256, model, pages)
    if storage.exists(key):
        payload = json.loads(storage.read_text(key))
        payload["from_cache"] = True
        return payload

    edital, usage = call_llm(pages, model)
    payload = {
        "sha256": sha256,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "pages_used": [p["page_number"] for p in pages],
        "input_hash": input_hash(pages),
        "usage": usage,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "edital": edital.model_dump(),
    }
    storage.write_text(key, json.dumps(payload, ensure_ascii=False, indent=2))
    payload["from_cache"] = False
    return payload


# ---------------------------------------------------------------------------
# Payload -> linhas da silver
# ---------------------------------------------------------------------------


def _iso_date_or_none(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None  # data malformada vira null em vez de quebrar a carga


def payload_to_rows(payload: dict, original_filename: str | None) -> tuple[dict, list[dict]]:
    e = payload["edital"]
    meta = {
        "sha256": payload["sha256"],
        "model": payload["model"],
        "prompt_version": payload["prompt_version"],
        "extracted_at": payload["extracted_at"],
    }
    edital_row = {
        **meta,
        "original_filename": original_filename,
        **{k: e.get(k) for k in ("orgao", "numero_edital", "banca_organizadora", "esfera", "uf", "municipio",
                                 "taxa_inscricao_min", "taxa_inscricao_max", "documento_completo", "observacoes")},
        **{k: _iso_date_or_none(e.get(k)) for k in ("data_publicacao", "inscricao_inicio", "inscricao_fim", "data_prova")},
        "qtd_cargos": len(e.get("cargos", [])),
        "pages_used": payload["pages_used"],
        "input_tokens": payload["usage"]["input_tokens"],
        "output_tokens": payload["usage"]["output_tokens"],
    }
    cargo_rows = []
    for i, c in enumerate(e.get("cargos", [])):
        c = dict(c)
        # Regra determinística: total de carreira/grupo não é vaga do cargo.
        grupo = bool(c.pop("vagas_referem_se_ao_grupo", False))
        c["vagas_total_grupo"] = c["vagas_total"] if grupo else None
        if grupo:
            c["vagas_total"] = None
            c["vagas_ampla_concorrencia"] = None
        cargo_rows.append({**meta, "cargo_idx": i, "vagas_referem_se_ao_grupo": grupo, **c})
    return edital_row, cargo_rows
