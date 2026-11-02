"""DAG da Silver: bronze.edital_paginas -> texto limpo -> extração com LLM.

    clean_pages ──► pending_editais ──► extract (1 task por edital) ──► load_extractions
       (grátis)        (respeita max_editais)     (OpenAI + cache)        (silver.editais / silver.cargos)

Proteções de custo:
- `max_editais` (default 1): no máximo N editais chamam o LLM por execução.
- `max_input_tokens`: teto de tokens de entrada por edital (só páginas relevantes).
- Cache no lake por (sha256, modelo, versão do prompt): reexecutar não paga de novo.
"""

from __future__ import annotations

from datetime import datetime

from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException
from airflow.models.param import Param


@dag(
    dag_id="silver_editais",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    max_active_tasks=2,  # no máximo 2 chamadas simultâneas à OpenAI
    tags=["editais", "silver", "llm"],
    doc_md=__doc__,
    params={
        "max_editais": Param(1, type="integer", minimum=0, maximum=50, description="Máx. de editais enviados ao LLM"),
        "max_input_tokens": Param(20000, type="integer", minimum=2000, maximum=100000),
        "filename": Param("", type="string", description="Opcional: processa só estes arquivos, separados por vírgula (ex.: tce_sp.pdf,ufg.pdf)"),
    },
)
def silver_editais():
    @task
    def clean_pages() -> int:
        """bronze -> silver.edital_paginas (limpeza determinística, custo zero)."""
        from datetime import timezone

        from editais.cleaning import clean_page_text
        from editais import warehouse as wh

        done = wh.existing_keys(wh.SILVER_PAGES, "sha256")
        rows = wh.query(
            f"SELECT sha256, original_filename, page_number, text FROM `{wh.table_id(wh.BRONZE_PAGES)}`"
        )
        now = datetime.now(timezone.utc).isoformat()
        out = []
        for r in rows:
            if r["sha256"] in done:
                continue
            txt = clean_page_text(r["text"])
            out.append({"sha256": r["sha256"], "original_filename": r["original_filename"],
                        "page_number": r["page_number"], "text_clean": txt, "char_count": len(txt),
                        "cleaned_at": now})
        n = wh.load_rows(wh.SILVER_PAGES, out)
        print(f"{n} páginas limpas carregadas em silver.edital_paginas")
        return n

    @task
    def pending_editais(_cleaned: int, params: dict | None = None) -> list[dict]:
        from editais import warehouse as wh
        from editais.llm_extraction import PROMPT_VERSION, default_model

        model = default_model()
        done = wh.existing_keys(
            wh.SILVER_EDITAIS, "sha256", "model = @m AND prompt_version = @v", {"m": model, "v": PROMPT_VERSION}
        )
        rows = wh.query(
            f"SELECT sha256, ANY_VALUE(original_filename) AS original_filename, SUM(char_count) AS chars "
            f"FROM `{wh.table_id(wh.SILVER_PAGES)}` GROUP BY sha256 ORDER BY chars"
        )
        todo = [r for r in rows if r["sha256"] not in done]
        if params["filename"]:
            wanted = {f.strip() for f in params["filename"].split(",") if f.strip()}
            todo = [r for r in todo if r["original_filename"] in wanted]
        todo = todo[: params["max_editais"]]
        print(f"modelo={model} prompt={PROMPT_VERSION} | já extraídos: {len(done)} | nesta execução: "
              f"{[r['original_filename'] for r in todo]}")
        if not todo:
            raise AirflowSkipException("Nada pendente para extrair")
        return [{"sha256": r["sha256"], "original_filename": r["original_filename"]} for r in todo]

    @task(retries=1)
    def extract(item: dict, params: dict | None = None) -> dict:
        from editais import warehouse as wh
        from editais.config import get_settings
        from editais.llm_extraction import extract_with_cache, payload_to_rows
        from editais.page_selection import estimate_tokens, select_pages
        from editais.storage import get_storage

        pages = wh.query(
            f"SELECT page_number, text_clean FROM `{wh.table_id(wh.SILVER_PAGES)}` "
            f"WHERE sha256 = @sha ORDER BY page_number",
            {"sha": item["sha256"]},
        )
        chosen = select_pages(pages, max_tokens=params["max_input_tokens"])
        est = sum(estimate_tokens(p["text_clean"]) for p in chosen)
        print(f"{item['original_filename']}: {len(chosen)}/{len(pages)} páginas selecionadas (~{est} tokens)")

        from editais.grounding import ground_cargos
        from editais.llm_extraction import build_user_content

        payload = extract_with_cache(item["sha256"], chosen, get_storage(get_settings()))
        edital_row, cargo_rows = payload_to_rows(payload, item["original_filename"])
        cargo_rows = ground_cargos(cargo_rows, build_user_content(chosen))
        suspeitos = [c["nome"] for c in cargo_rows if c["vagas_no_texto"] is False or c["salario_no_texto"] is False]
        if suspeitos:
            print(f"⚠️  números não encontrados no texto (suspeitos): {suspeitos}")
        print(f"{'CACHE' if payload['from_cache'] else 'LLM'} | tokens in={payload['usage']['input_tokens']} "
              f"out={payload['usage']['output_tokens']} | {len(cargo_rows)} cargos | órgão: {edital_row['orgao']}")
        return {"edital": edital_row, "cargos": cargo_rows}

    @task
    def load_extractions(results: list[dict]) -> dict:
        from editais import warehouse as wh

        results = list(results)
        n_e = wh.load_rows(wh.SILVER_EDITAIS, [r["edital"] for r in results])
        n_c = wh.load_rows(wh.SILVER_CARGOS, [c for r in results for c in r["cargos"]])
        tok_in = sum(r["edital"]["input_tokens"] or 0 for r in results)
        tok_out = sum(r["edital"]["output_tokens"] or 0 for r in results)
        print(f"silver.editais +{n_e} | silver.cargos +{n_c} | tokens in={tok_in} out={tok_out}")
        return {"editais": n_e, "cargos": n_c, "input_tokens": tok_in, "output_tokens": tok_out}

    load_extractions(extract.expand(item=pending_editais(clean_pages())))


silver_editais()
