"""DAG da Fase 1: landing (PDFs soltos) -> data lake raw + manifesto da execução.

Fluxo:
    list_pdfs  ->  ingest (1 task por PDF, dynamic task mapping)  ->  manifest (JSONL no lake)
                                                                  ->  load_bigquery (bronze.ingestion_manifest)
                                                                  ->  pages_to_bigquery (bronze.edital_paginas)
"""

from __future__ import annotations

from datetime import datetime

from airflow.datasets import Dataset
from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException

from editais.pipeline_datasets import BRONZE_PAGINAS


@dag(
    dag_id="ingest_editais",
    start_date=datetime(2026, 1, 1),
    schedule=None,  # disparo manual por enquanto; depois pode virar @daily
    catchup=False,
    tags=["editais", "fase-1", "ingestao"],
    doc_md=__doc__,
)
def ingest_editais():
    @task
    def list_pdfs() -> list[str]:
        from editais.config import get_settings
        from editais.ingestion import list_landing_pdfs

        pdfs = list_landing_pdfs(get_settings().landing_dir)
        if not pdfs:
            raise AirflowSkipException("Nenhum PDF em data/landing/")
        return pdfs

    @task(retries=2)
    def ingest(pdf_path: str) -> dict:
        from editais.config import get_settings
        from editais.ingestion import ingest_pdf, record_to_dict
        from editais.storage import get_storage

        storage = get_storage(get_settings())
        record = ingest_pdf(pdf_path, storage)
        print(f"[{record.status}] {record.original_filename} -> {record.lake_uri}")
        return record_to_dict(record)

    @task
    def manifest(records: list[dict], run_id: str | None = None) -> dict:
        from editais.config import get_settings
        from editais.ingestion import write_manifest
        from editais.storage import get_storage

        records = list(records)
        uri = write_manifest(records, get_storage(get_settings()), run_id or "manual")
        summary = {s: sum(r["status"] == s for r in records) for s in {r["status"] for r in records}}
        print(f"Manifesto: {uri} | Resumo: {summary}")
        return summary

    @task
    def load_bigquery(records: list[dict], run_id: str | None = None) -> int:
        from editais.warehouse import bq_enabled, load_manifest

        if not bq_enabled():
            raise AirflowSkipException("GCP_PROJECT_ID não definido: pulando carga no BigQuery")
        n = load_manifest(list(records), run_id or "manual")
        print(f"{n} linhas carregadas em editais_bronze.ingestion_manifest")
        return n

    @task(outlets=[Dataset(BRONZE_PAGINAS)])
    def pages_to_bigquery(records: list[dict]) -> dict:
        """Lake -> BigQuery: extrai o texto de cada PDF e carrega 1 linha por página."""
        import tempfile

        from editais.config import get_settings
        from editais.ingestion import raw_key_for
        from editais.storage import get_storage
        from editais.text_extraction import extract_pages
        from editais.warehouse import bq_enabled, load_pages, loaded_page_hashes

        if not bq_enabled():
            raise AirflowSkipException("GCP_PROJECT_ID não definido: pulando carga no BigQuery")

        valid = {r["sha256"]: r for r in records if r["status"] != "rejected_invalid_pdf"}
        already = loaded_page_hashes()
        todo = [r for sha, r in valid.items() if sha not in already]
        print(f"{len(valid)} PDFs válidos | {len(valid) - len(todo)} já no BigQuery | {len(todo)} a carregar")
        if not todo:  # sem página nova, não dispara a silver (que pode chamar o LLM)
            raise AirflowSkipException("Nenhum PDF novo para carregar")

        storage = get_storage(get_settings())
        rows = []
        with tempfile.TemporaryDirectory() as tmp:
            for r in todo:
                pdf = storage.local_path(raw_key_for(r["sha256"]), tmp)
                rows += extract_pages(pdf, r["sha256"], r["original_filename"])

        n = load_pages(rows)
        ocr = sum(row["needs_ocr"] for row in rows)
        print(f"{n} páginas carregadas em editais_bronze.edital_paginas ({ocr} sem texto: possível OCR)")
        return {"pdfs": len(todo), "paginas": n, "paginas_sem_texto": ocr}

    records = ingest.expand(pdf_path=list_pdfs())
    manifest(records)
    load_bigquery(records)
    pages_to_bigquery(records)


ingest_editais()
